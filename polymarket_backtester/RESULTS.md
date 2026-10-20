# Observed results

Requested window: September 19–October 18, 2026, inclusive, in UTC-08:00. The first 20 calendar days are development and the final 10 are validation.

| Data check | Result |
| --- | ---: |
| Actual resolved markets downloaded | 2,880 / 2,880 |
| Actual contract-price observations, both outcomes | 86,095 |
| Available exact BTC minute observations / reported boundaries | 39,325 / 46,080 |
| Complete 0–15 reference paths | 1,894 / 2,880 |
| Markets eligible for labeled trend research | 2,155 / 2,880 |
| Settlement mismatches where checkable | 0 |
| Uncheckable settlement metadata | 3 |
| Historical ask/depth snapshots | 0 |

The reference is the **Chainlink BTC/USD 60-second TWAP stream** specified in each market's actual rules. Missing paths and missing points were not synthesized. Historical contract observations have irregular timestamps: only six observations across both outcomes and all requested entry times fall exactly on their target second. Prior actual observations are kept separately with timestamps and ages; they are not advertised as exact-minute purchase quotes.

The prespecified sign-of-slope predictor fitted to minutes 1–10 produced:

| Sample | Correct / eligible | Accuracy | 95% whole-day bootstrap interval |
| --- | ---: | ---: | ---: |
| Development | 1,013 / 1,345 | 75.32% | 73.65%–76.98% |
| Final 10 days | 613 / 810 | 75.68% | 73.30%–78.36% |

The development-selected constant-Up baseline was 50.37% accurate on validation. The trend signal predicts direction substantially better than that baseline in the available sample. This is **not** evidence that buying the corresponding contract has positive expected value: the contract's price already reflects the likely outcome, and data gaps may bias the sample.

The development search tested 192 prespecified strategy combinations. Of these, 101 had at least an 80% in-sample win rate and 50 had positive scenario P&L with the explicit execution assumptions. **None passed the prespecified search-adjusted advantage screen.** No optimized strategy was selected or evaluated on the holdout. This does not establish that every possible strategy loses; it means this search did not establish a sufficiently supported trade rule.

Strict executable backtests cannot establish returns without historical asks and sufficient depth for $100 fills. Scenario mode uses real history but assumes fills, half-spread, slippage and historical applicability of archived fee metadata. Its returns must not be described as demonstrated executable profits. No real-world profitability or consistent automated trading advantage has been demonstrated, and no real trades were placed.

The dashboard supports inspecting markets, regression plots, reference-price gaps, development-only threshold adjustments, entry-time comparisons, all strategy metrics, and scenario cumulative P&L/drawdown. The frozen validation panel records the decision to select no optimized rule. Full machine-readable results and provenance are in the dataset's audit, research report and raw response receipts.
