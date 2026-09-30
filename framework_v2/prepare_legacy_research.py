"""Prepare a new, pinned research run from local legacy data, never alter sources.

Date-only availability is an explicit end-of-day research convention authorized
for workflow validation, not proof of historical publication or provider vintage.
"""
from __future__ import annotations
import argparse
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import platform
import pandas as pd
import pyarrow.parquet as pq
from .source_catalog import identity
from .universe_repair import canonicalize
from .financial_events import canonicalize_financial_events
from .legacy_provider import BuiltinFactors, REQUIRED_DATASETS
from .local_io import write_new


def date_convention(values):
    dates = pd.to_datetime(values, format='mixed', errors='raise')
    if isinstance(dates.dtype, pd.DatetimeTZDtype):
        dates = dates.dt.tz_convert('Asia/Tokyo').dt.tz_localize(None)
    return dates.dt.normalize().dt.tz_localize('Asia/Tokyo') + pd.Timedelta(hours=23, minutes=59)


def build(cache, raw_root, out, start, end, capital):
    from runtime.jquants_cache_builder import normalize_jquants_statements
    cache, raw_root, out = Path(cache), Path(raw_root), Path(out)
    out.mkdir(parents=True, exist_ok=False)
    begin, finish = pd.Timestamp(start), pd.Timestamp(end)
    warmup = begin - pd.Timedelta(days=460)
    contract = {'experiment_id': 'legacy_real_data_workflow_v1',
        'scope': 'full dated universe; quality+dual_ma v2 integration; not old composite equivalence',
        'interval': [start, end], 'window_class': 'previously_inspected_diagnostic',
        'capital_jpy': capital, 'top_n': 10, 'rebalance': 'weekly_last_supplied_session',
        'clock': 'same_day_23:59_features; next_observed_session_open_execution; no_extra_D1_lag',
        'availability_policy': 'date_only_end_of_day_research_convention; financial_disclosure_JST',
        'historical_publication_verified': False, 'historical_vintage_verified': False,
        'fees': '10bps commission + 5bps each-side execution slippage',
        'instruments': '100-share lot assumption; historical instrument audit deferred',
        'pricing': 'unadjusted OHLC; cash dividends/corporate-action accounting audit deferred',
        'missing_policy': 'drop missing factor score; skip missing open or unaffordable gap; no resizing',
        'source_policy': 'conflicting rows quarantined; explicit SHA256 snapshots',
        'readiness': 'RESEARCH-ONLY', 'external_submission': False,
        'python': platform.python_version()}
    write_new(out/'contract.json', contract)  # Before any outcome inspection.
    sources, frames, repairs = [], {}, {}
    def read(name):
        path = cache/(name+'.parquet')
        sources.append(identity(path))
        return pd.read_parquet(path)
    print('preparing prices and dated universe', flush=True)
    prices = read('prices')
    prices['date'] = pd.to_datetime(prices['date'], format='mixed')
    prices = prices.loc[prices.date.between(warmup, finish+pd.Timedelta(days=10))].copy()
    prices['code'] = prices.code.astype(str)
    prices = prices.drop_duplicates()
    ambiguous = prices.duplicated(['date','code'], keep=False)
    repairs['price_conflict_rows'] = int(ambiguous.sum())
    prices.loc[ambiguous].to_parquet(out/'price_quarantine.parquet', index=False)
    prices = prices.loc[~ambiguous].copy()
    for column in ('open','high','low','close','volume'):
        if 'adjustment_'+column in prices:
            prices['adjustment_'+column] = prices[column]
    prices['available_at'] = date_convention(prices.date)
    universe, quarantine, repairs['universe'] = canonicalize(read('universe'))
    quarantine.to_json(out/'universe_quarantine.jsonl', orient='records', lines=True)
    universe['asof_date'] = pd.to_datetime(universe.asof_date)
    # Include the preceding membership snapshot, plus all changes in the test window.
    previous = universe.loc[universe.asof_date.le(begin), 'asof_date'].max()
    universe = universe.loc[universe.asof_date.between(previous, finish)].copy()
    universe['available_at'] = date_convention(universe.asof_date)
    frames['universe'] = universe
    codes = set(universe.loc[universe.in_universe, 'code'])
    prices = prices.loc[prices.code.isin(codes)].copy()
    frames['prices'] = prices
    print('preparing original financial disclosures', flush=True)
    parts = []
    for year in range(warmup.year, finish.year+1):
        for path in sorted((raw_root/'statements'/str(year)).glob('*/*.parquet')):
            day = pd.Timestamp(path.stem)
            if warmup <= day <= finish:
                sources.append(identity(path))
                parts.append(pd.read_parquet(path))
    if not parts:
        raise ValueError('no original financial disclosure objects for the interval')
    with redirect_stdout(StringIO()):
        financial = normalize_jquants_statements(pd.concat(parts, ignore_index=True))
    financial = financial.loc[financial.code.isin(codes)].reset_index(drop=True)
    financial, quarantine, repairs['financial_events'] = canonicalize_financial_events(financial)
    # Equal-time events have no trustworthy ordering; keep them in evidence, not silently last-wins.
    ambiguity = financial.duplicated(['code', 'source_disclosed_at'], keep=False)
    ties = financial.loc[ambiguity].copy()
    ties['quarantine_reason'] = 'simultaneous_disclosures_no_ordering'
    quarantine = pd.concat([quarantine, ties], ignore_index=True)
    repairs['simultaneous_financial_rows'] = int(ambiguity.sum())
    quarantine.to_parquet(out/'financial_quarantine.parquet', index=False)
    financial = financial.loc[~ambiguity].copy()
    financial['available_at'] = financial.source_disclosed_at
    frames['financial_summary'] = financial
    caps = read('market_cap')
    caps['asof_date'] = pd.to_datetime(caps.asof_date, format='mixed')
    caps = caps.loc[caps.asof_date.between(warmup, finish) & caps.code.isin(codes)].copy()
    caps = caps.drop_duplicates()
    ambiguous = caps.duplicated(['asof_date','code'], keep=False)
    repairs['market_cap_conflict_rows'] = int(ambiguous.sum())
    caps.loc[ambiguous].to_parquet(out/'market_cap_quarantine.parquet', index=False)
    caps = caps.loc[~ambiguous].copy()
    caps['available_at'] = date_convention(caps.asof_date)
    frames['market_cap'] = caps
    print('pinning Parquet snapshots and configurations', flush=True)
    manifest = {'format':'snapshot.parquet.v1', 'datasets':{}}
    for name, frame in frames.items():
        frame.to_parquet(out/(name+'.parquet'), index=False)
        file_id = identity(out/(name+'.parquet'))
        manifest['datasets'][name] = {'path':name+'.parquet', 'sha256':file_id['sha256'], 'rows':len(frame)}
    write_new(out/'snapshot.json', manifest)
    builtin = BuiltinFactors()
    references = []
    for name in ('quality','dual_ma'):
        implementation = ('public.momentum_12_1' if name == 'residual_momentum' else 'public.'+name)
        references.append(name+'.json')
        write_new(out/(name+'.json'), {'schema_version':'1.0','id':name,'kind':'factor','version':'realdata1',
            'implementation':{'id':implementation,'version':builtin.versions[implementation],'parameters':{}},
            'lookback':460,'data_requirements':[{'dataset':d,'fields':list(frames[d].columns)} for d in REQUIRED_DATASETS[name]],
            'output':{'name':name,'description':'Actual legacy data, workflow research replay'}})
    write_new(out/'strategy.json', {'schema_version':'1.0','id':'legacy_real_workflow','kind':'strategy','version':'1',
        'universe':{'snapshot':'universe'},'factors':references,'scoring':{'formula':'quality + dual_ma'},
        'portfolio':{'construction':'equal_weight','parameters':{'top_n':10,'long_gross':0.9,'preprocess':'zscore','missing_policy':'drop'}},
        'risk':{'max_position_weight':0.1,'max_gross_exposure':1,'turnover_budget':1,'allow_short':False},
        'rebalance':{'frequency':'weekly'}})
    write_new(out/'account.json', {'account_id':'legacy-research-only','revision':'0','equity':str(capital),
        'available_cash':str(capital),'positions':[]})
    write_new(out/'backtest.json', {'schema_version':'1.0','id':'legacy_real_data_workflow','kind':'run','version':'1',
        'strategy':'strategy.json','data_snapshot':'snapshot.json','account_ref':'account.json',
        'clock':{'start':start,'end':end,'timezone':'Asia/Tokyo'},'mode':'backtest',
        'fees':{'commission_rate':0.001,'minimum_fee':0},'output_dir':'results'})
    dates = sorted(prices.date.unique())
    sessions = []
    for i, day in enumerate(dates[:-1]):
        if not begin <= day <= finish:
            continue
        next_day = pd.Timestamp(dates[i+1])
        decision = pd.Timestamp(day).strftime('%Y-%m-%d')+'T23:59:00+09:00'
        now = next_day.strftime('%Y-%m-%d')+'T09:00:00+09:00'
        known = prices.loc[prices.date.le(day)].sort_values('date').groupby('code').tail(1)
        actual = prices.loc[prices.date.eq(next_day)]
        quotes = [{'code':r.code,'bid':str(r.close),'ask':str(r.close),'asof':now}
            for r in known.itertuples() if pd.notna(r.close) and r.close>0]
        execution = [{'code':r.code,'bid':str(r.open*0.9995),'ask':str(r.open*1.0005),'asof':now}
            for r in actual.itertuples() if pd.notna(r.open) and r.open>0]
        instruments = [{'code':q['code'],'lot_size':100,'tick_size':'0.1'} for q in quotes]
        sessions.append({'decision_at':decision,'now':now,'quotes':quotes,
                         'execution_quotes':execution,'instruments':instruments})
    write_new(out/'timeline.json', {'format':'execution.daily_bars.v2','sessions':sessions})
    source_checks = [identity(item['path']) == item for item in sources]
    if not all(source_checks): raise ValueError('source changed during preparation')
    write_new(out/'source_receipt.json', {'sources':sources,'repairs':repairs,
        'code':{p.name:identity(p)['sha256'] for p in Path(__file__).parent.glob('*.py')},
        'snapshot':identity(out/'snapshot.json'),'timeline':identity(out/'timeline.json'),
        'planning_quotes_semantics':'model_reference_previous_close_not_observed_intraday_quotes',
        'sessions':len(sessions), 'universe_codes':len(codes),'readiness':'RESEARCH-ONLY'})
    print(json.dumps({'output':str(out),'sessions':len(sessions),'codes':len(codes),
        'rows':{name:len(frame) for name,frame in frames.items()},'repairs':repairs}), flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cache', required=True); p.add_argument('--raw-root', required=True)
    p.add_argument('--out', required=True); p.add_argument('--start', required=True); p.add_argument('--end', required=True)
    p.add_argument('--capital', type=int, default=2000000)
    a=p.parse_args(); build(a.cache,a.raw_root,a.out,a.start,a.end,a.capital)


if __name__=='__main__': main()
