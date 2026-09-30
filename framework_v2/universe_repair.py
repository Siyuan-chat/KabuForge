"""Canonicalize legacy membership keys; quarantine conflicts, never infer PIT time."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import pandas as pd
from .source_catalog import identity


def canonicalize(frame):
    required = ['asof_date', 'code', 'in_universe']
    missing = set(required) - set(frame.columns)
    if missing:
        raise ValueError('missing membership columns: ' + ','.join(sorted(missing)))
    result = frame[required].copy()
    result['source_row'] = range(len(frame))
    dates = pd.to_datetime(result['asof_date'], format='mixed', errors='coerce')
    if isinstance(dates.dtype, pd.DatetimeTZDtype):
        raise ValueError('membership effective date must be a local calendar date')
    valid_date = dates.notna() & dates.eq(dates.dt.normalize())
    valid_code = result['code'].map(lambda v: isinstance(v, str) and bool(v.strip()))
    valid_member = result['in_universe'].map(lambda v: isinstance(v, bool))
    valid = valid_date & valid_code & valid_member
    rejected = result.loc[~valid].copy()
    rejected['reason'] = 'invalid_date_code_or_membership'
    result = result.loc[valid].copy()
    result['asof_date'] = dates.loc[valid].dt.strftime('%Y-%m-%d')
    result['code'] = result['code'].str.strip()
    keys = ['asof_date', 'code']
    groups = result.groupby(keys, dropna=False)['in_universe']
    conflict = groups.transform('nunique').gt(1)
    conflicts = result.loc[conflict].copy()
    conflicts['reason'] = 'conflicting_membership'
    quarantine = pd.concat([rejected, conflicts], ignore_index=True)
    accepted = result.loc[~conflict]
    clean = accepted.groupby(keys + ['in_universe'], as_index=False).agg(
        source_row_count=('source_row', 'size'))
    clean = clean.sort_values(keys).reset_index(drop=True)
    stats = {'input_rows': len(frame), 'canonical_rows': len(clean),
        'collapsed_identical_membership_rows': len(accepted) - len(clean),
        'quarantined_rows': len(quarantine), 'conflicting_keys':
        len(conflicts[keys].drop_duplicates()), 'invalid_rows': len(rejected),
        'available_at_verified': False, 'historical_version_verified': False,
        'pit_executable': False}
    return clean, quarantine, stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    source = identity(args.input)
    frame = pd.read_parquet(args.input, columns=['asof_date', 'code', 'in_universe'])
    clean, quarantine, stats = canonicalize(frame)
    # Verify the source did not change while this separate derivative was built.
    if identity(args.input) != source:
        raise ValueError('input changed during normalization')
    clean.to_parquet(out / 'membership.parquet', index=False)
    quarantine.to_json(out / 'quarantine.jsonl', orient='records', lines=True, date_format='iso')
    receipt = {'format': 'legacy.membership_repair.v1', 'input': source, 'stats': stats,
        'membership': identity(out / 'membership.parquet'),
        'quarantine': identity(out / 'quarantine.jsonl'),
        'implementation': identity(__file__),
        'time_semantics': 'effective_date_only_no_publication_timestamp',
        'scope': 'core_membership_projection_not_sector_or_scale_metadata'}
    with (out / 'receipt.json').open('x', encoding='utf-8') as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'out': str(out), **stats}))


if __name__ == '__main__':
    main()
