"""Four fixed workflows with fictional bars; no market-performance evidence."""
from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
import hashlib
import json
import math
from pathlib import Path

from framework_v2.local_cache import load_research_bars
from framework_v2.research_application import ResearchApplicationService


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root = args.out.resolve()
    root.mkdir(parents=True, exist_ok=False)
    days = []
    day = date(2024, 1, 1)
    while len(days) < 100:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day += timedelta(days=1)
    source = root / 'fictional-bars.csv'
    codes = ['4502', '6758', '8306']
    with source.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['Date', 'Code', 'Open', 'High',
            'Low', 'Close', 'Volume', 'AdjustmentFactor', 'AdjustmentClose'])
        writer.writeheader()
        for n, code in enumerate(codes):
            for i, text in enumerate(days):
                close = 100 + 25*n + i*(0.13+n*0.03) + math.sin(i/(3+n))*(1+n)
                writer.writerow(dict(Date=text, Code=code, Open=close*0.999,
                    High=close*1.01, Low=close*0.99, Close=close, Volume=100000+i,
                    AdjustmentFactor=1, AdjustmentClose=close))
    manifest = load_research_bars(source, codes=codes, start_date=days[0],
        end_date=days[-1], price_basis='raw').freeze(root / 'frozen-input')
    service = ResearchApplicationService(root, enable_paper=True)
    momentum = service.run_price_research(manifest, dict(signal_template='price_momentum',
        lookback=20, count=2, frequency='monthly', cash=2000000.0, fee=0.1,
        fast_period=5, slow_period=20, signal_provider='native'))
    diagnostics = service.run_factor_diagnostics_task(manifest)
    features = Path(diagnostics['result']['report']['artifacts']['feature_rows'])
    portfolio = service.run_factor_strategy(manifest, features,
        score_source='factor_feature_rows', expected_artifact_sha256=sha(features))
    report = Path(portfolio['result']['report_path'])
    paper = service.create_historical_paper(manifest, report, sha(report),
        enable_paper=True, call_id='canonical-create', idempotency_key='canonical-create')
    replay = service.run_historical_paper_all(paper['account_dir'], enable_paper=True,
        call_id='canonical-replay', idempotency_key='canonical-replay')
    results = dict(fixture='fictional weekday bars; not an exchange calendar',
        readiness='RESEARCH-ONLY', pit_guarantee=False, manifest_sha256=sha(manifest),
        momentum=momentum, factor_diagnostics=diagnostics,
        factor_to_portfolio=portfolio, historical_paper_replay=replay)
    (root / 'canonical-results.json').write_text(
        json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    print(json.dumps(dict(status='COMPLETED', evidence=str(root / 'canonical-results.json'),
        readiness='RESEARCH-ONLY', pit_guarantee=False)))


if __name__ == '__main__':
    main()
