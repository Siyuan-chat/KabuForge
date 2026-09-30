"""Read-only legacy provenance discovery. Reports are NOT executable PIT inputs.

Paths are explicit; no recursive workspace scan, data rewrite or network fallback.
Current byte equality never certifies the input version of a historical run.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PureWindowsPath

TABLES = ('prices', 'universe', 'financial_summary', 'market_cap',
          'index_prices', 'margin', 'sector')


def identity(path):
    path = Path(path)
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f'input changed during hashing: {path}')
    return {'path': str(path.resolve()), 'bytes': after.st_size,
            'sha256': digest.hexdigest()}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def mapped_path(recorded, old_root, new_root):
    """Component based migration candidate; never a version equivalence claim."""
    recorded, old = PureWindowsPath(recorded), PureWindowsPath(old_root)
    relative = recorded.relative_to(old)  # Reject unrelated drives/roots.
    if '..' in relative.parts:
        raise ValueError('parent traversal in recorded path')
    return Path(new_root).joinpath(*relative.parts)


def inventory_runs(roots):
    records = []
    for root in map(Path, roots):
        for directory in sorted(root.iterdir()):
            if not directory.is_dir():
                continue
            config = directory / 'config_used.json'
            record = {'run_id': directory.name, 'run_path': str(directory),
                      'config_status': 'missing', 'historical_input_binding': 'unproven'}
            if config.is_file():
                try:
                    value = read_json(config)
                    cli = value.get('cli', {})
                    record.update(config_status='read', config_identity=identity(config),
                                  recorded_data_dir=cli.get('data_dir'),
                                  start=cli.get('start'), end=cli.get('end'))
                except (ValueError, OSError, AttributeError) as exc:
                    record.update(config_status='invalid', error=type(exc).__name__)
            # No returns, holdings, labels or credential-bearing config fields copied.
            record['evidence_files'] = [name for name in
                ('manifest.json', 'input_manifest.json', 'run_status.json', 'logs.txt')
                if (directory / name).is_file()]
            records.append(record)
    return records


def cache_profile(root):
    import pyarrow.parquet as pq
    root = Path(root)
    result = {'root': str(root), 'exists': root.is_dir(), 'tables': {}}
    manifest = root / 'manifest.json'
    if manifest.is_file():
        value = read_json(manifest)
        result['manifest'] = {**identity(manifest), 'updated_at': value.get('updated_at'),
                              'time_semantics': 'batch_metadata_not_row_availability'}
    for name in TABLES:
        path = root / (name + '.parquet')
        if not path.is_file():
            continue
        meta = pq.ParquetFile(path)
        columns = meta.schema_arrow.names
        result['tables'][name] = {**identity(path), 'rows': meta.metadata.num_rows,
            'columns': columns, 'availability_status': 'unverified',
            'available_at_column': 'available_at' in columns,
            'version_chain_status': 'unverified'}
    return result


def compare_caches(left, right):
    records = []
    for name in sorted(set(left['tables']) | set(right['tables'])):
        a, b = left['tables'].get(name), right['tables'].get(name)
        state = ('missing_side' if a is None or b is None else
                 'identical_current_bytes' if a['sha256'] == b['sha256'] else 'different_bytes')
        records.append({'dataset': name, 'status': state,
                        'left_sha256': a and a['sha256'], 'right_sha256': b and b['sha256'],
                        'historical_run_version_proven': False})
    return records


def snapshot_profile(path):
    value = read_json(path)
    rule = value.get('rules', {}).get('universe')
    return {**identity(path), 'anchor_date': value.get('anchor_date'),
            'cache_version': value.get('cache_version'), 'created_at': value.get('created_at'),
            'universe_rule': rule, 'historical_membership_verified': False,
            'blockers': ['CURRENT_CONSTITUENTS'] if rule == 'TOPIX_CURRENT_CONSTITUENTS'
                        else ['MEMBERSHIP_PROVENANCE_UNVERIFIED']}


def raw_profile(path):
    """Profile explicit raw Parquet only; disclosure events do not certify delivery."""
    import pyarrow.parquet as pq
    import pandas as pd
    meta = pq.ParquetFile(path)
    names = meta.schema_arrow.names
    result = {**identity(path), 'rows': meta.metadata.num_rows, 'columns': names,
              'available_at_verified': False, 'response_log_binding': 'unproven'}
    for key in ('Date', 'DiscDate', 'DisclosedDate', 'date', 'disclosed_date'):
        if key in names:
            values = pq.read_table(path, columns=[key]).column(0).to_pandas().dropna()
            result[key] = {'min': str(values.min()) if len(values) else None,
                           'max': str(values.max()) if len(values) else None}
    for date_key, time_key in (('DiscDate', 'DiscTime'), ('DisclosedDate', 'DisclosedTime'),
                               ('disclosed_date', 'disclosed_time')):
        if date_key in names and time_key in names:
            frame = pq.read_table(path, columns=[date_key, time_key]).to_pandas()
            stamp = pd.to_datetime(frame[date_key].astype(str) + ' ' +
                                   frame[time_key].astype(str), errors='coerce')
            valid = stamp.notna()
            result['disclosure_events'] = {'valid_rows': int(valid.sum()),
                'invalid_rows': int((~valid).sum()), 'source_timezone': 'Asia/Tokyo',
                'meaning': 'source_disclosure_event_not_local_delivery',
                'min': stamp[valid].min().tz_localize('Asia/Tokyo').isoformat() if valid.any() else None,
                'max': stamp[valid].max().tz_localize('Asia/Tokyo').isoformat() if valid.any() else None}
            break
    return result


def request_profile(path):
    """Do not export params, tokens, error bodies or pagination values."""
    fields, endpoints, statuses = set(), Counter(), Counter()
    rows = invalid = 0
    times = []
    with Path(path).open(encoding='utf-8-sig') as stream:
        for line in stream:
            if not line.strip():
                continue
            rows += 1
            try:
                value = json.loads(line)
                fields.update(value)
                endpoints[str(value.get('endpoint'))] += 1
                statuses[str(value.get('status_code'))] += 1
                stamp = datetime.fromisoformat(value['timestamp'].replace('Z', '+00:00'))
                if stamp.tzinfo is None or stamp.utcoffset() is None:
                    raise ValueError('naive acquisition timestamp')
                times.append(stamp.astimezone(timezone.utc))
            except (ValueError, KeyError, TypeError, AttributeError):
                invalid += 1
    return {**identity(path), 'rows': rows, 'invalid_records_or_timestamps': invalid,
            'fields': sorted(fields), 'endpoints': dict(endpoints), 'statuses': dict(statuses),
            'min_acquired_at': min(times).isoformat() if times else None,
            'max_acquired_at': max(times).isoformat() if times else None,
            'time_semantics': 'acquisition_not_historical_publication',
            'raw_response_binding': 'unverified', 'available_at_verified': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-root', action='append', required=True)
    parser.add_argument('--cache-pair', nargs=2, action='append', required=True,
                        metavar=('OLD', 'CURRENT'))
    parser.add_argument('--snapshot-metadata', action='append', default=[])
    parser.add_argument('--raw-sample', action='append', default=[])
    parser.add_argument('--request-log', action='append', default=[])
    parser.add_argument('--old-root', required=True)
    parser.add_argument('--new-root', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    report = {'format': 'legacy.source_catalog.v1',
              'generated_at': datetime.now(timezone.utc).isoformat(),
              'historical_replay_ready': False, 'runs': [], 'caches': {}, 'comparisons': [],
              'snapshots': [], 'raw_samples': [], 'request_logs': [], 'errors': [],
              'blockers': ['RUN_TIME_INPUT_HASH_BINDING_UNVERIFIED',
                           'ROW_AVAILABILITY_AND_VERSION_CHAIN_UNVERIFIED']}
    try:
        report['runs'] = inventory_runs(args.run_root)
        for run in report['runs']:
            if run.get('recorded_data_dir'):
                try:
                    run['migration_candidate'] = str(mapped_path(run['recorded_data_dir'],
                                                                 args.old_root, args.new_root))
                except ValueError:
                    run['migration_candidate'] = None
        for old, current in args.cache_pair:
            for root in (old, current):
                if root not in report['caches']:
                    report['caches'][root] = cache_profile(root)
            report['comparisons'].append({'old': old, 'current': current,
                'datasets': compare_caches(report['caches'][old], report['caches'][current])})
        report['snapshots'] = [snapshot_profile(p) for p in args.snapshot_metadata]
        report['raw_samples'] = [raw_profile(p) for p in args.raw_sample]
        report['request_logs'] = [request_profile(p) for p in args.request_log]
    except Exception as exc:
        report['errors'].append({'type': type(exc).__name__, 'message': str(exc)})
    report['run_counts'] = dict(Counter(r['config_status'] for r in report['runs']))
    with (out / 'catalog.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({'output': str(out / 'catalog.json'), 'run_counts': report['run_counts'],
                      'comparisons': report['comparisons'], 'errors': report['errors'],
                      'historical_replay_ready': False}, ensure_ascii=False))
    return 1 if report['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
