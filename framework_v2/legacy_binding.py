"""Recover recorded input facts from one legacy log, without inventing timestamps."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
from .source_catalog import identity, read_json


def log_facts(text):
    writes, dates = {}, []
    request_range = None
    for number, line in enumerate(text.splitlines(), 1):
        match = re.search(r'cache write done table=(\w+) path=(.*?) rows=(\d+)', line)
        if match:
            name, path, rows = match.groups()
            writes[name] = {'recorded_path': path, 'recorded_rows': int(rows), 'log_line': number}
        match = re.search(r'request_range=(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})', line)
        if match:
            request_range = list(match.groups())
        match = re.search(r'cache (?:miss|hit) listed_info snapshot=(\d{8})', line)
        if match:
            key = match[1]
            date = f'{key[:4]}-{key[4:6]}-{key[6:]}'
            if date not in dates:
                dates.append(date)
    return {'recorded_tables': writes, 'request_range': request_range,
            'listed_snapshot_dates': dates}


def audit(run_dir, cache_root):
    import pandas as pd
    import pyarrow.parquet as pq
    run, cache = Path(run_dir), Path(cache_root)
    log = run / 'logs.txt'
    config = run / 'config_used.json'
    facts = log_facts(log.read_text(encoding='utf-8-sig'))
    report = {'format': 'legacy.input_evidence.v1', 'run_id': run.name,
        'config': identity(config), 'log': identity(log), **facts, 'datasets': {},
        'historical_version_verified': False, 'historical_available_at_verified': False,
        'status': 'BLOCKED', 'errors': [],
        'blockers': ['NO_CONTEMPORANEOUS_INPUT_DIGEST', 'NO_PRICE_PUBLICATION_VERSION_EVIDENCE',
                     'NO_UNIVERSE_PUBLICATION_VERSION_EVIDENCE']}
    report['recorded_data_dir'] = read_json(config).get('cli', {}).get('data_dir')
    for name, record in facts['recorded_tables'].items():
        current = cache / (name + '.parquet')
        if current.is_file():
            count = pq.ParquetFile(current).metadata.num_rows
            report['datasets'][name] = {'current_rows': count,
                'recorded_rows': record['recorded_rows'],
                'row_count_matches_run': count == record['recorded_rows'],
                'historical_binding': 'unproven'}
    shards, frames = [], []
    for date in facts['listed_snapshot_dates']:
        path = cache / 'listed_info' / (date + '.parquet')
        if not path.is_file():
            report['errors'].append('missing snapshot: ' + str(path))
            continue
        frame = pq.read_table(path).to_pandas()
        required = {'asof_date', 'code', 'in_universe'}
        if not required.issubset(frame.columns):
            report['errors'].append('unsupported snapshot schema: ' + str(path))
            continue
        normalized = frame[['asof_date', 'code', 'in_universe']].copy()
        normalized['asof_date'] = pd.to_datetime(normalized['asof_date'])
        matches_date = bool(normalized['asof_date'].eq(pd.Timestamp(date)).all())
        shards.append({**identity(path), 'rows': len(frame), 'date_matches_name': matches_date,
            'requested_snapshot_date': date,
            'effective_dates': sorted(normalized['asof_date'].dt.strftime('%Y-%m-%d').unique().tolist()),
            'available_at': None, 'time_status': 'event_date_only',
            'historical_version_verified': False})
        if normalized['asof_date'].gt(pd.Timestamp(date)).any():
            report['errors'].append('snapshot effective date exceeds request date: ' + str(path))
        frames.append(normalized)
    if frames:
        combined = pd.concat(frames, ignore_index=True)
        duplicate_count = int(combined.duplicated(['asof_date', 'code']).sum())
        current = pq.read_table(cache / 'universe.parquet',
                               columns=['asof_date', 'code', 'in_universe']).to_pandas()
        current['asof_date'] = pd.to_datetime(current['asof_date'])
        current = current[current['asof_date'].isin(combined['asof_date'].unique())]
        keys = ['asof_date', 'code']
        current_duplicates = int(current.duplicated(keys).sum())
        comparison = {'shard_rows': len(combined), 'current_rows_on_dates': len(current),
            'duplicate_keys': duplicate_count, 'current_duplicate_keys': current_duplicates,
            'matches_logged_row_count': len(combined) == facts['recorded_tables'].get(
                'universe', {}).get('recorded_rows'), 'equality_scope': 'current files only'}
        if not duplicate_count and not current_duplicates:
            left, right = combined.set_index(keys).sort_index(), current.set_index(keys).sort_index()
            common = left.index.intersection(right.index)
            a, b = left.loc[common, 'in_universe'], right.loc[common, 'in_universe']
            comparison.update(shard_only_keys=len(left.index.difference(right.index)),
                current_only_keys=len(right.index.difference(left.index)),
                differing_membership=int((~(a.eq(b) | (a.isna() & b.isna()))).sum()))
        report['universe_reconstruction'] = comparison
    report['universe_shards'] = shards
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    parser.add_argument('--cache', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    report = audit(args.run, args.cache)
    with (out / 'input_evidence.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({'output': str(out / 'input_evidence.json'), 'status': report['status'],
        'universe_reconstruction': report.get('universe_reconstruction'),
        'errors': report['errors']}, ensure_ascii=False))
    # A blocked audit must not be mistaken for an executable input approval.
    return 2 if report['status'] == 'BLOCKED' else 0


if __name__ == '__main__':
    raise SystemExit(main())
