# Bitcoin 15-minute Polymarket research

A local, read-only Python collector, research engine and Streamlit dashboard. No wallet access, private-key storage, order submission, or real trades. Historical observations come from actual Polymarket responses. Missing data stays missing.

Read [RESULTS.md](RESULTS.md) for the actual collected coverage and research findings.

## Run

```bash
cd /workspace/polymarket-btc-backtester
bash scripts/setup.sh
.venv/bin/python -m pm_btc.cli collect --end-date 2026-10-19
.venv/bin/python -m pm_btc.cli verify data/2026-09-19_2026-10-19_Etc-GMT+8
.venv/bin/python -m pm_btc.cli analyze data/2026-09-19_2026-10-19_Etc-GMT+8
bash scripts/start.sh
```

On another machine, open this project directory, create a virtual environment with Python 3.11 or newer, install `requirements.lock`, and run `python -m streamlit run app.py` using that environment. The scripts above target this cloud workspace explicitly.

The collector defaults to the last 30 **complete calendar days in UTC-08:00**, the user's client timezone. The pinned example covers September 19–October 18, 2026, inclusive; the end date is exclusive. Pass `--timezone UTC` for complete UTC days instead. All source requests and CSV timestamps use UTC. A normal 30-day window contains 2,880 expected 15-minute intervals.

Collection returns exit code **2** when requirements remain incomplete, even when useful real data was saved. Exit code 0 from `verify` means file hashes match, not that the dataset is complete. `--max-markets N` is a diagnostic limit; it never changes the full requested interval count or supplies nonexistent data. Successful responses are cached on disk so interrupted runs can resume. The default source client limits request starts to 20/second, retries transient failures at most twice, and retains TLS verification.

## Data and provenance

Each window under `data/` contains:

| File | Contents |
| --- | --- |
| `markets.csv` | Expected intervals, discovery status, actual market IDs, start/end, token IDs, rules, resolution, reported opening and settlement, fee metadata |
| `reference_minutes.csv` | Exact observed reference prices at minutes 0–15; unavailable observations are blank |
| `contract_history.csv` | Actual historical observations for both outcome tokens with original timestamps |
| `contract_targets.csv` | Exact observations when present, separate last-known observations and ages at minutes 10–13, missing historical asks/depth |
| `trades.csv` | Actual executed trade prints used as an alternative when contract histories are missing |
| `issues.csv` | Discovery, API, reference-validation and completeness failures |
| `audit.json` | Coverage counts, missing-data limitations, integrity hashes and analysis eligibility |
| `requests.jsonl`, `raw/` | Public request provenance and original responses with SHA-256 receipts |
| `features.csv` | Validated causal feature rows, when analysis has run |
| `training_strategies.csv` | Every strategy tested on development data |
| `frozen_research.json` | Frozen rule, assumptions, search definition and input/engine signature |
| `research_report.json` | Baseline accuracy, exclusion counts and any frozen scenario validation |

**An expected interval is not a downloaded market.** CSV rows representing missing intervals never manufacture prices or outcomes. The separate `last_observation_price` is an actual earlier observation, not an estimated exact-minute contract price. Neither historical observations nor executed trade sizes establish an available ask or market depth. Down prices are collected independently rather than inferred as `1 - Up`.

The downloaded markets' rules identify **Chainlink BTC/USD 60-second TWAP**. The collector verifies the stream URL, market configuration, duration, outcome ordering and tie rule (Up on equality). It queries the same public historical chart route used by Polymarket with `twapEnabled=true` and `twapLookbackSeconds=60`. It cross-checks observed endpoint prices against resolved event metadata. Spot or exchange candles are not substituted for this TWAP stream. Actual opening/settlement values from event metadata can supply boundary rows, with their distinct provenance; interior gaps are never filled.

The public chart endpoint has returned empty or partial historical paths, including the oldest requested intervals. See the current audit for exact coverage. Analysis uses only validated available paths; results cannot be described as a complete 30-day study when gaps remain. Missingness can bias conclusions.

Source details and investigated alternatives are recorded in [docs/sources.md](docs/sources.md).

## Analysis and execution limits

The predictor is the sign of a linear regression fitted to minutes 1–10. Features include slope, regression fit, opening-price distance, percentage change, 1/2/3/5-minute momentum, volatility, directional consistency and reversal count/magnitude. Entry-time features use observations no later than minute 10, 11, 12 or 13 as appropriate. Flat trends abstain; incomplete feature windows are excluded rather than interpolated.

The strategy grid is prespecified and searches **development data only**. The first 20 requested calendar days are development; the final 10 are held out, even if early days have missing observations. A rule needs at least 60 training trades, positive modeled P&L and a search-adjusted Wilson lower confidence bound above the most conservative break-even threshold in its trades. If no rule qualifies, the optimized strategy holdout stays unrun. A prespecified trend-only baseline is evaluated separately.

The chosen rule (or decision to choose none) is written before any optimized holdout evaluation. Its signature fixes the dataset, engine and execution assumptions. Rerunning with changed inputs refuses to reuse the exposed holdout. Dashboard threshold changes affect development data only; they do not alter the frozen experiment. Retuning based on holdout results requires new future validation data.

**Strict execution mode** requires historical asks and at least $100 of observed ask-side depth. These public historical sources do not supply such order-book snapshots, so strict execution may have zero trades and no P&L result.

**Scenario mode** uses actual last-observed contract history, bounded to at most 90 seconds old, plus an explicit assumed half-spread and slippage. Defaults add $0.005/share for each, or one cent total. It assumes sufficient liquidity; it is not evidence of an executable fill. The fee schedule comes from each resolved market's archived metadata. Historical immutability of that metadata is an additional assumption. Current live fees or current books are never presented as historical evidence.

The supported observed fee schedule has exponent 1: `fee_per_share = rate * price * (1 - price)`. Unknown schedules are excluded. Each trade spends a fixed **$100 including fees**, with `shares = 100 / (purchase_price + fee_per_share)`. A win redeems one dollar per share; a loss loses the full $100. No maker rebates are assumed. Profit metrics include wins/losses, purchase prices, average win/loss, net scenario P&L, deployed-capital ROI, dollar maximum drawdown, profit factor, EV, fees and a share-weighted break-even rate. This ROI is not a funded-account return. The break-even rate is descriptive for a mix of entry prices, not a guarantee that a given unweighted win rate is profitable.

Wilson intervals and binomial tests are reported with independence caveats; paired comparison uses a majority predictor selected on development data. Whole-day bootstrap intervals retain dependence within days. Ten validation days remain a small number of independent blocks. Fee assumptions, missingness and unobserved execution cannot be solved by a narrow statistical interval. **Positive scenario P&L does not demonstrate real-world profitability or a reliable trading advantage.**

## Checks

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
```

Test fixtures are artificial numerical/API examples used only to verify parsing, no-look-ahead behavior, missingness, fee math, budget accounting and application behavior. They never enter the actual research dataset or establish profitability.

The application separates source collection, normalization, reference validation, research and presentation. Future execution adapters can be added as a separate authorized task; no trading adapter is implemented here.
