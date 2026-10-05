---
doc_id: gui_research_courses
version: 1
locale: en_US
---

# KabuForge GUI research courses (real local market data)

These five courses document workflows executed from the public-candidate source checkout in Qt, with real GUI rendering in Chinese, Japanese, and English. The 219 screenshots are public-source captures, not screenshots of an installed wheel; they do not certify clean-wheel installation or optional-runtime acceptance. The public build defaults Regime Off and excludes the private state-machine bridge. Chart 19 in this reference report is Off/unavailable with zero traces, not a qualified internal state trajectory. Users select their own CSV/Parquet/manifest. No market bars or account data are bundled.

The five workflows use the same selected local J-Quants daily bars, while distinct completed manifests are bound to different source runs. Reading and calculating real history does not prove historical availability. Every run remains **RESEARCH-ONLY with `pit_guarantee=false`**. Historical Paper is a replayed research ledger, not forward simulation. Broker mapping is local and does not connect, submit, or cancel.

<!-- section:contract -->
## Shared input identity and fixed settings

The three language editions use the same identity and settings. Hashes identify artifacts; raw bars, daily details, account state, and complete reports remain in private local evidence.

```text
codes=4502,6758,8306
reference_window=2017-01-01..2022-12-31
reference_observed_window=2017-01-04..2022-12-30
input=explicit user-selected local CSV/Parquet/snapshot/completed manifest
bundled_market_data=none
cache_ma_gui_manifest_sha256=from_local_cache_or_MA_receipt
reference_research_manifest_sha256=from_selected_research_run_receipt
public_media_manifest=docs/demos/research-20261006/media_manifest.json
public_media_manifest_sha256=from_current_acceptance_receipt
manifest_relation=distinct_bytes; same_4392_selected_raw_rows
price_basis=raw
MA_fast_slow=20/60
momentum_window=20
factor_windows=20/60; direction=positive; weights=0.5/0.5
factor_label=execution_open_to_fifth_observed_session_open
minimum_cross_section=3; quantiles=3
portfolio=top2; rebalance=monthly; initial_cash_JPY=2000000; one_way_fee=0.001
model_split=train=2017-2019; validation=2020; historical_test=2021-2022; seed=42
benchmark=local TOPIX price index; price-only; no dividends
pit_guarantee=false; status=RESEARCH-ONLY
```

The securities and window were fixed for the current execution and corporate-action limits, not selected by return. Freezing merges only explicitly allowed exact duplicates and excludes only the 2020-10-01 all-day halt placeholders verified by the JPX notice. Other conflicts or missing values are rejected, never dropped, forward-filled, or fabricated. TOPIX is the actual local price index, aligned exactly to strategy valuation dates; gaps are not filled and dividends are excluded.
The cache import/MA freeze and downstream research runs may bind byte-distinct manifests even when they select the same 4,392 raw-bar rows. Read each run's actual manifest SHA from its cache, job, or report receipt; never reuse one operation's hash as another's identity. Exact identities for the captured reference examples are listed in `EVIDENCE_SUMMARY.md` in the packaged docs. The screenshot index is identified by the current `media_manifest.json` and its acceptance receipt.

## Start and freeze the bars

Start the public-source workbench and choose a language. The sidebar includes Home, My Strategies, Data Center, Backtest Results, Paper Trading, Broker Connections, and Run History. In “Data Center → Local market cache · Offline research input”, follow five checkpoints: (1) select one explicit file or completed manifest; (2) choose codes, dates, and research price basis; (3) inspect coverage, source identity, and hash; (4) review the explicit identical-duplicate and verified-halt policies; (5) validate, freeze, and reverify the new manifest. The reference cache receipt records 8,172 selected rows before deduplication, removes 3,777 fully identical rows, excludes only the three all-null 2020-10-01 TSE halt placeholders, then retains 4,392 rows across 1,464 dates. Conflicting rows or other missing values fail closed; they are not dropped or filled. A language change does not change the input or run identity.

This course uses existing local J-Quants history. Data Center also offers explicit connection-test/download actions, but they are separate and not required here. The course does not read credentials or make network requests. A separate download date would not prove historical `available_at`.

The public evidence summary describes the Qt capture provenance and exact identities without shipping the source Parquet or complete manifests. Use the receipt belonging to each run to confirm its input SHA; the reference window is 2017-01-04 through 2022-12-30, 1,464 common observed dates.

For each cache task, retain and inspect the job request, launch, result, exit, and stdout/stderr records. Confirm the requested selection, duplicate/halt counts, retained coverage, and final manifest SHA. Run history points to the local evidence; screenshots alone are not a receipt.

![Select local market data](../demos/research-20261006/en_US/cache-selection.png) ![Validated and frozen input](../demos/research-20261006/en_US/cache-frozen.png)

Open “User Manual” to search the complete course text. Search “Demo 1” to open the first course; search “broker” and open the result to jump to Demo 5. Manual links and images are local resources. Search and language switching do not start a research job.

![Open Demo 1 in the manual](../demos/research-20261006/en_US/manual-course-demo-1.png) ![Search for broker and jump to Demo 5](../demos/research-20261006/en_US/manual-search-broker.png)

## Demo 1: price momentum, MA 20/60, and indicators

In “My Strategies”, create a research strategy from “Price momentum (downloaded data)”, select the frozen input, and keep the fixed 20-session momentum, monthly rebalance, two holdings, JPY 2,000,000 initial cash, and 0.1% one-way fee. For the separate crossover example, choose “MA crossover (prior close / next open)” with fast/slow periods 20/60. Do not change windows after viewing NAV. Run preflight and then the backtest.

Signals use the previous observed close and earlier data; share quantities are fixed at the prior close and execute at the next observed open. Process sells before buys on the same date. If an opening gap leaves insufficient cash, skip the entire frozen order rather than resizing it. Mark NAV at raw close. Native and TA-Lib MA outputs should match financially for the same frozen recipe; the indicator provider does not alter strategy accounting. The reference momentum report covers 1,464 observations, with 161 fill orders and 22 skipped orders. Use those counts only when input, recipe, and report identity exactly match; order count is not closed-trade count.

Open “Backtest Results” and check input SHA, dates, cash/holdings, fills, skip reasons, and fees. Read the price chart as separate prior-close scheduled signals, actual opening fills, and skipped orders. A fill marker is not a signal price. The model excludes dividends, slippage, market impact, and round lots. Historical PIT is unverified; this is not new OOS evidence or PAPER-READY.

![Native MA inputs](../demos/research-20261006/en_US/ma-native-configured.png) ![Native MA results](../demos/research-20261006/en_US/ma-native-results.png) ![TA-Lib MA inputs](../demos/research-20261006/en_US/ma-talib-configured.png) ![TA-Lib MA results](../demos/research-20261006/en_US/ma-talib-results.png)

Separately, open “Data Center → Technical indicator research” and choose the same manifest and one code. Run TA-Lib or pandas-ta only when the panel has an available runtime receipt. Set SMA 20, RSI 14, ATR 14, MACD 12/26/9 and calculate. Read price/SMA in JPY per share, RSI on a fixed 0–100 axis, MACD line/signal/histogram, and ATR in JPY per share. Warm-up values remain empty and lines break at gaps; no interpolation is applied. ATR uses complete OHLC in the selected price basis. The pandas-ta receipt records its actual provider default warm-up SMA seed. The two providers may differ slightly by version and initialization; use the provider, version, and parameters in the receipt. Native is the MA strategy calculation path, not a general RSI/MACD/ATR indicator provider. Indicators do not automatically become signals or orders.

![TA-Lib controls](../demos/research-20261006/en_US/indicator-talib-controls.png) ![TA-Lib price and SMA](../demos/research-20261006/en_US/indicator-talib-price-sma.png) ![TA-Lib RSI](../demos/research-20261006/en_US/indicator-talib-rsi.png) ![TA-Lib MACD](../demos/research-20261006/en_US/indicator-talib-macd.png) ![TA-Lib ATR](../demos/research-20261006/en_US/indicator-talib-atr.png)

![pandas-ta controls](../demos/research-20261006/en_US/indicator-pandas_ta-controls.png) ![pandas-ta price and SMA](../demos/research-20261006/en_US/indicator-pandas_ta-price-sma.png) ![pandas-ta RSI](../demos/research-20261006/en_US/indicator-pandas_ta-rsi.png) ![pandas-ta MACD](../demos/research-20261006/en_US/indicator-pandas_ta-macd.png) ![pandas-ta ATR](../demos/research-20261006/en_US/indicator-pandas_ta-atr.png)

For failures, check code uniqueness, complete OHLC, integer periods, warm-up coverage, and the isolated runtime receipt. Do not move optional dependencies into the GUI's NumPy/pandas environment. Retry into a new run directory and preserve the failed evidence.

## Demo 2: factor features and separate evaluation

In “Data Center → Factor diagnostics · RESEARCH-ONLY”, choose the same frozen manifest. Fix 20- and 60-session momentum, positive direction with 0.5 weights, rank normalization, minimum cross-section 3, three quantiles, and a five-observation forward label before running.

![Factor workbench](../demos/research-20261006/en_US/factor-workbench.png) ![Frozen features and recipe](../demos/research-20261006/en_US/factor-input-and-recipe.png)

Check the feature/recipe page first. `feature_rows` are computable through the signal date's D-1 close and are stored separately from evaluation labels. A label is the simple return from execution open to the fifth subsequent observed-session open. It belongs only to the evaluation panel; unavailable tail labels remain missing and are not strategy features. Review daily IC/Rank IC, valid cross-section and coverage, quantile returns, quantile membership turnover, factor correlation, and descriptive year summaries. Constant factors, missing sections, and invalid dates must show a reason. Code-order tie breaking is deterministic display, not information. Three securities yield at most three quantiles; overlapping labels do not create independent observations. ICIR is a descriptive mean/std measure, not calibrated inference.

Never feed forward labels, quantile returns, or the evaluation panel to a strategy. Do not choose direction or weights from this historical window. Keep `contract.json`, `receipt.json`, `report.json`, and run logs for reproduction. If dates or coverage are incomplete, diagnose the receipt instead of dropping a security to make the panel look complete.

![IC and Rank IC](../demos/research-20261006/en_US/factor-ic-rank-ic.png) ![Quantile returns](../demos/research-20261006/en_US/factor-quantiles.png) ![Coverage](../demos/research-20261006/en_US/factor-coverage.png) ![Membership turnover](../demos/research-20261006/en_US/factor-turnover.png) ![Factor correlation](../demos/research-20261006/en_US/factor-correlation.png) ![Descriptive years](../demos/research-20261006/en_US/factor-observed-years.png)

## Demo 3: portfolio, fixed-split models, and engine candidates

Open “Data Center → Research Studio”. In “Strategy”, explicitly select `factor_feature_rows` (feature-only) or a completed model `predictions` file, then verify its byte SHA. Do not select evaluation/forward-label artifacts. Keep two holdings, monthly rebalance, JPY 2,000,000, 0.1% one-way fees, minimum cross-section 3, and the positive 20/60 composite weights of 0.5 each. After running, inspect signal and execution dates, actual fills/skips, and daily NAV.

![20/60 composite controls](../demos/research-20261006/en_US/studio-factor-composite-controls.png) ![Composite strategy results](../demos/research-20261006/en_US/studio-factor-composite-results.png)

In “Models”, select the frozen factor run and run both LightGBM and CatBoost fixed models. The split is train 2017–2019, validation 2020, historical diagnostics 2021–2022, seed 42, with label-end purging at boundaries. There is no random split, auto-tuning, or automatic model selection. Training-fit predictions are diagnostic only and must not enter strategy predictions. Verify the model is used only after its training-label cutoff. 2021–2022 is already observed history, not fresh OOS. Preserve split counts, purge counts, missing reasons, and model/prediction hashes. If an isolated dependency fails, use its stage and worker log; do not import it into the main process.

In “Engines”, inspect Native, VectorBT, and Backtrader reports separately for the same manifest and frozen order recipe. Candidates replay fixed quantities and must not copy Native NAV. Daily account tolerance and execution-stream equality are separate outcomes. Compare fill date, side, quantity, actual open price, fee, skips, and account path. Preserve cash and long-only semantic differences; close cash alone does not prove equal execution. A Backtrader next-bar market event is not a broker fill.

![Both-model controls](../demos/research-20261006/en_US/studio-both-models-controls.png) ![LightGBM score results](../demos/research-20261006/en_US/studio-lightgbm-score-results.png) ![CatBoost controls](../demos/research-20261006/en_US/studio-catboost-score-controls.png) ![CatBoost score results](../demos/research-20261006/en_US/studio-catboost-score-results.png) ![Both-model results](../demos/research-20261006/en_US/studio-both-models-results.png) ![Remaining model results](../demos/research-20261006/en_US/studio-both-models-remaining-results.png)

![Engine controls](../demos/research-20261006/en_US/studio-engines-20-60-controls.png) ![Engine summary](../demos/research-20261006/en_US/studio-engines-20-60-results.png) ![Remaining engine results](../demos/research-20261006/en_US/studio-engines-20-60-remaining-results.png)

Read the account path, order schedule, fee evidence, and report/source hashes before interpreting charts. The actual TOPIX price index excludes dividends and is comparable only on exactly aligned NAV dates; missing dates make relative statistics unavailable. The dashboard has 19 figures: 15 overview figures, 3 per-security price/execution figures, and 1 Regime-state figure. In this report that figure is Off/unavailable with zero traces and no qualified state trajectory. Fee and execution-delay sensitivity runs use a separate panel and are not included in these 19 figures. All outputs remain RESEARCH-ONLY/PIT false.

## Reading results: jQuantStats and the price/execution chart

First confirm report model, sampling frequency, dates, price basis, fees, TOPIX source, and `pit_guarantee=false`. jQuantStats analyzes N−1 adjacent NAV return intervals and excludes initial capital to the first NAV. Native NAV and whole-window return use the source report's initial-capital basis; do not mix the denominators. Daily annualization uses 252 periods only when the report declares `daily`; irregular observed dates are not a verified JPX calendar.

The dashboard presents 15 overview groups in order: jQuantStats adjacent-NAV return snapshot; source-report NAV; underwater drawdown; monthly-return heatmap; observed annual windows; rolling return/volatility/Sharpe; strategy-versus-TOPIX cumulative return; period-return distribution; cash/holding weights; FIFO closed-trade returns net of fees; cumulative realized P&L; cumulative actual fees; gross two-sided turnover; holdings count/maximum weight/HHI; and verified security-price contribution. Per-security price diagnostics follow, plus a Regime panel. In this report it is Off/unavailable with zero traces; another report must contain qualified historical inputs to show a populated timeline. Annual plots show observed windows, not necessarily complete calendar years. jQuantStats uses N−1 adjacent NAV intervals and excludes initial capital to first NAV. 252-period daily annualization applies only when the report declares `daily`. Hover for date, value, unit, axis, and missing intervals. Order, fill, and completed position-cycle counts differ.

Read the separate price/execution figure as raw price/indicator, prior-close scheduled order, actual open fill, and skipped order. Signal date precedes execution date; fill price is the open, not the signal price. TOPIX is a price index without dividends, not total return. Do not deduct recorded fees twice. Gross turnover includes both buy and sell notional; it is not one-way turnover. Orders, fills, and completed position cycles are distinct counts.

![jQuantStats snapshot](../demos/research-20261006/en_US/dashboard-chart-01.png) ![Monthly heatmap](../demos/research-20261006/en_US/dashboard-chart-04.png) ![TOPIX comparison](../demos/research-20261006/en_US/dashboard-chart-07.png) ![Price, signal, and execution](../demos/research-20261006/en_US/dashboard-chart-16.png) ![Regime Off, unavailable, zero traces](../demos/research-20261006/en_US/dashboard-chart-19.png)

Links to all 19 images: [01 jQuantStats](../demos/research-20261006/en_US/dashboard-chart-01.png) · [02 NAV](../demos/research-20261006/en_US/dashboard-chart-02.png) · [03 drawdown](../demos/research-20261006/en_US/dashboard-chart-03.png) · [04 monthly](../demos/research-20261006/en_US/dashboard-chart-04.png) · [05 observed annual windows](../demos/research-20261006/en_US/dashboard-chart-05.png) · [06 rolling risk](../demos/research-20261006/en_US/dashboard-chart-06.png) · [07 TOPIX](../demos/research-20261006/en_US/dashboard-chart-07.png) · [08 return distribution](../demos/research-20261006/en_US/dashboard-chart-08.png) · [09 holdings/cash](../demos/research-20261006/en_US/dashboard-chart-09.png) · [10 closed-trade returns](../demos/research-20261006/en_US/dashboard-chart-10.png) · [11 realized P&L](../demos/research-20261006/en_US/dashboard-chart-11.png) · [12 fees](../demos/research-20261006/en_US/dashboard-chart-12.png) · [13 gross turnover](../demos/research-20261006/en_US/dashboard-chart-13.png) · [14 concentration](../demos/research-20261006/en_US/dashboard-chart-14.png) · [15 price contribution](../demos/research-20261006/en_US/dashboard-chart-15.png) · [16 4502 price/execution](../demos/research-20261006/en_US/dashboard-chart-16.png) · [17 6758 price/execution](../demos/research-20261006/en_US/dashboard-chart-17.png) · [18 8306 price/execution](../demos/research-20261006/en_US/dashboard-chart-18.png) · [19 Regime Off/unavailable, zero traces](../demos/research-20261006/en_US/dashboard-chart-19.png)

![Native MA results](../demos/research-20261006/en_US/ma-native-results.png) ![TA-Lib MA results](../demos/research-20261006/en_US/ma-talib-results.png)

Concentration, contribution, and a populated Regime timeline appear only when supported by report evidence. This capture's Regime panel is Off/unavailable with zero traces. Charts explain a run; they do not validate a strategy.

### Fee and execution-delay sensitivity: bind a report and run all scenarios

In “Backtest Results”, open a completed source `report.json` and confirm its strategy and input identity. Check that the sensitivity panel’s source path and SHA256 match the selected report, then click “Run all three fixed scenarios”. The fixed source report hashes are Native MA `Native MA report (SHA bound locally)`, TA-Lib MA `TA-Lib MA report (SHA bound locally)`, and price momentum `price-momentum report (SHA bound locally)`. The momentum source is a root-prepared offline research report, not a GUI-created run receipt. The report bytes remain unchanged. Switching the interface language redraws the existing output and does not rerun it.

The result contains three rows and three NAV curves. The 0.1% case reruns the fixed recipe. The 0.2% case reruns the same strategy and bars with a higher fee, recalculating prior-close order quantities. “+1 observed session” keeps baseline quantities fixed and executes at the next actual observed open; it is an execution-timing diagnostic, not a new signal/selection or a strategy to prefer. All cases cover 2017-01-04 through 2022-12-30 (1,464 observations).

| Fixed source | Scenario | Orders | Fills/skips | Fees JPY | Ending NAV | Ending cash/equity JPY | Max drawdown |
|---|---|---:|---:|---:|---:|---:|---:|
| Native MA | 0.1% baseline | 64 | 45/19 | 64,251.25 | 1.10859189 | 13.94/2,217,183.77 | -30.70% |
| Native MA | 0.2% rerun | 64 | 45/19 | 126,492.57 | 1.07504194 | 13.53/2,150,083.89 | -31.38% |
| Native MA | +1 session, fixed quantity | 64 | 30/34 | 34,828.99 | 2.16391987 | 146,472.52/4,327,839.74 | -31.63% |
| TA-Lib MA | 0.1% baseline | 64 | 45/19 | 64,251.25 | 1.10859189 | 13.94/2,217,183.77 | -30.70% |
| TA-Lib MA | 0.2% rerun | 64 | 45/19 | 126,492.57 | 1.07504194 | 13.53/2,150,083.89 | -31.38% |
| TA-Lib MA | +1 session, fixed quantity | 64 | 30/34 | 34,828.99 | 2.16391987 | 146,472.52/4,327,839.74 | -31.63% |
| Price momentum | 0.1% baseline | 183 | 161/22 | 92,328.74 | 1.38670855 | 1,276,821.14/2,773,417.11 | -33.10% |
| Price momentum | 0.2% rerun | 184 | 168/16 | 182,846.64 | 1.25358260 | 9,737.31/2,507,165.19 | -41.32% |
| Price momentum | +1 session, fixed quantity | 183 | 128/55 | 59,240.38 | 1.32007157 | 192,816.23/2,640,143.15 | -38.01% |

Native MA and TA-Lib MA have identical financial paths across the three scenarios for this fixed input. Do not prefer the delayed case because its ending NAV appears higher. Check all three rows and curves, fees, fills/skips, ending values, and drawdowns. The private task records request/source hashes and worker launch/result/exit logs; the public evidence summary gives the comparison without publishing daily JSON. Monetary figures are displayed to two decimal places; compare the bound report/account path rather than rounded display.

![Native MA sensitivity panel](../demos/research-20261006/en_US/sensitivity-native-workbench.png) ![Native MA three scenarios](../demos/research-20261006/en_US/sensitivity-native-results.png)
![TA-Lib MA sensitivity panel](../demos/research-20261006/en_US/sensitivity-talib-workbench.png) ![TA-Lib MA three scenarios](../demos/research-20261006/en_US/sensitivity-talib-results.png)
![Momentum sensitivity panel](../demos/research-20261006/en_US/sensitivity-momentum-workbench.png) ![Momentum three scenarios](../demos/research-20261006/en_US/sensitivity-momentum-results.png)

## Demo 4: step, full replay, and read-only historical Paper

Choose “Paper Trading” in the sidebar, then the first tab, “Historical market research replay”. Do not use “Legacy advanced features”. Select the same frozen manifest, a completed price/composite strategy report, and a new, not-yet-existing account directory. Review starting cash, schedule, and source identity; choose “Create isolated account”. Never choose an existing production ledger.

“Open and verify” is read-only. Use “Step one day” to process one next date. On a no-fill date, check skip/cash/NAV evidence rather than assuming the run failed. On an actual fill date, compare signal date, execution date, next open, side, quantity, and fee. “Run full history” processes the remaining observations in order. The completion receipt should cover all 1,464 observed dates through 2022-12-30; use the report and receipt, not the requested calendar-day span. Compare completion state, account summary, fills/skips/fees with the source strategy report.

![Create the isolated account](../demos/research-20261006/en_US/paper-created.png) ![Advance one observed date](../demos/research-20261006/en_US/paper-one-observed-day.png) ![Actual fill date](../demos/research-20261006/en_US/paper-actual-trade-day.png) ![Full-history replay](../demos/research-20261006/en_US/paper-full-history.png) ![Last observed date](../demos/research-20261006/en_US/paper-last-observed-day.png) ![Reopen and read-only refresh](../demos/research-20261006/en_US/paper-reopened-readonly.png)

Close and reopen the same teaching account; run “Open and verify” and “Read-only refresh”. Queries do not advance the cursor, and retrying the same cursor/idempotency key must not duplicate events or fills. Changed manifest, report bytes, selected bars, or replay implementation identity must fail closed. Find local request/result/exit records and logs in the GUI task/history view; the public summary contains no ledger or daily account data. Replay time is not source `available_at`; continuous-share research does not prove forward Paper, historical visibility, board lots, or broker execution.

## Demo 5: test endpoint, order mapping, and read-only boundary

Choose “Broker Connections” → first tab, “Offline cash-equity mapping preview”. The capability table is in the second advanced tab. Create a new workspace and choose test endpoint `http://127.0.0.1:18081`. Enter an explicit local account label/type, exchange, and credential-reference string; never enter the secret itself. “Save offline configuration” writes local configuration only and does not resolve a reference or issue a token.

Use a teaching `OrderIntent`: code 6758, buy, quantity 100, lot size 100, tick size 1, and a valid Tokyo `DAY` timestamp. Supply the course's fixed teaching estimate/fee/account/time; never treat a cached historical price as a live quote. Click “Generate local mapping preview”. Expect mapped locally / not connected / not submitted, a local receipt containing the input identity, and `network_calls=0`. There are no submit, cancel, or token controls in this lesson.

The captured mapping uses test port 18081, account type 4 (specified account), and exchange 9 (SOR). Reference price, fee, account label, and teaching clock come from the fixed local course configuration.

![Test endpoint configuration](../demos/research-20261006/en_US/broker-test-config.png) ![Valid board-lot offline mapping](../demos/research-20261006/en_US/broker-valid-local-mapping.png)

Change quantity to 101 and preview again. Expect a lot-size block and `network_calls=0`. Failure evidence contains a redacted error code and does not store an order payload. Restore a valid lot multiple to preview again. Test configuration, valid mapping, 101-share block, and missing-reference diagnostic screenshots have all been captured in each locale and archived.

Read-only connection check is a separate action. For its explicit missing-reference negative path, put the unique expected-to-be-undefined reference `env:DEMO_MISSING_TOKEN` in the test config, save it, and click “Read-only check”. The worker should stop at credential resolution with `credential_missing` and zero GET requests. Only the reference name is persisted, never the secret value. This is a failed diagnostic, not a successful connection. A resolvable reference would start a localhost GET worker and may contact the terminal, so it is not used in this course. The missing-reference diagnostic is captured in all three locales and archived. A workflow-implemented label does not prove the actual terminal is connected; production port 18080 is not used.

<!-- section:evidence -->
## Screenshot, receipt, and log index

All 219 images are actual Qt captures of the public-candidate source build, rendered in each locale. They are not private-workbench screenshots and do not certify an installed wheel. The 19 dashboard figures are 15 overview charts, 3 per-security price/execution charts, and one Regime chart; sensitivity is a separate panel. The media manifest records the image paths and hashes.

| Course | Planned path (`{locale}` is `zh_CN`, `ja_JP`, or `en_US`) |
|---|---|
| Cache | `../demos/research-20261006/{locale}/cache-{selection,frozen}.png` |
| MA | `../demos/research-20261006/{locale}/ma-{native,talib}-{configured,results}.png` |
| Dashboard | `../demos/research-20261006/{locale}/dashboard-chart-01.png` through `dashboard-chart-19.png`; 16–18 are 4502/6758/8306 price/execution views, 19 shows Regime Off/unavailable with zero traces |
| Indicators | `../demos/research-20261006/{locale}/indicator-{talib,pandas_ta}-{controls,price-sma,rsi,macd,atr}.png` |
| Factor | `../demos/research-20261006/{locale}/factor-{input-and-recipe,ic-rank-ic,quantiles,coverage,turnover,correlation,observed-years}.png` |
| Studio | `../demos/research-20261006/{locale}/studio-factor-composite-{controls,results}.png`, `studio-both-models-{controls,results,remaining-results}.png`, `studio-lightgbm-score-results.png`, `studio-catboost-score-{controls,results}.png`, and `studio-engines-20-60-{controls,results,remaining-results}.png` |
| Historical Paper | `../demos/research-20261006/{locale}/paper-{created,one-observed-day,actual-trade-day,full-history,last-observed-day,reopened-readonly}.png` |
| Broker | `../demos/research-20261006/{locale}/broker-{test-config,valid-local-mapping,blocked-101,readonly-missing-reference}.png` (all archived) |
| Sensitivity | `../demos/research-20261006/{locale}/sensitivity-{native,talib,momentum}-{workbench,results}.png` |
| Manual search | `../demos/research-20261006/{locale}/manual-course-demo-1.png`, `manual-search-broker.png` |

The public evidence summary is `docs/demos/research-20261006/EVIDENCE_SUMMARY.md`; it describes only the provenance, scope, and limits of the published screenshots. Locate run logs through the GUI task/history view. The package does not include local requests, ledgers, detailed JSON, or user-specific absolute paths.
