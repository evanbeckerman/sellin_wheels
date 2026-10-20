# Open your Bitcoin research dashboard

This folder includes the application and its real historical dataset. It is separate from the original Sellin Wheels application. It does not connect to a wallet or place trades.

## Download from GitHub

1. Open the **codex/bitcoin-backtester** branch of this repository.
2. Click the green **Code** button, then **Download ZIP**.
3. Extract the downloaded ZIP. Open the extracted folder, then open **polymarket_backtester**.

## Windows

1. Install **Python 3.11 or newer** from https://www.python.org/downloads/ if it is not already installed. Enable **Add python.exe to PATH** during installation.
2. Double-click **RunDashboard.bat** inside this folder.
3. On the first run, wait while the launcher unpacks the dataset and installs packages. Keep its window open while using the dashboard.
4. Streamlit starts the dashboard and prints the local address to open in your browser. It usually opens the browser automatically.

## Mac or Linux

With Python 3.11 or newer installed, open a terminal in this folder and run:

```bash
python3 launch.py
```

Keep the terminal open while using the dashboard. Stop it with Ctrl+C. First launch needs internet access to download Python packages; reviewing the included study does not need a Polymarket account or API key.

## What to look at

- **Start here:** Follow the research checklist: inspect intervals, compare candidate rules, then check validation evidence. It reports actual study progress, not points or prediction-game scores.
- **Charts:** Choose a date and any 15-minute interval, then use Previous/Next to review the recorded BTC path. The chart includes the opening target, settlement, optional first-10-minute trend and entry-time markers. It uses the finest samples already stored, often 15 seconds apart, with a seconds-based axis. Missing stretches are not filled.
- **Data quality:** See what was collected and what is missing.
- **Market explorer:** Inspect real markets and the first-10-minute regression.
- **Trend analysis:** Compare predictions with settlements.
- **Development strategies / Strategy Lab:** Choose entry minute, minimum Bitcoin dollar gap above/below the opening target, and bid amount. Optionally require the first-10-minute trend to agree. Click **Test strategy** to review wins, losses, win rate, modeled net results and daily scenarios using the first 20 days only. Compare tested rules in the session scoreboard and export the results.
- **Frozen validation:** See why no optimized trading rule passed the prespecified screen.

The baseline predicted the final direction correctly in **613 of 810 usable validation markets (75.68%)**. That does **not** demonstrate profitable trading. Missing historical reference prices and historical order-book data are disclosed. Do not trade on these results.

### How the simplified Strategy Lab works

The minimum gap is a dollar distance, not a slope: with a $50 gap, the rule chooses Up when Bitcoin is at least $50 above its opening target and Down when it is at least $50 below. Markets inside the gap or exactly at the target are skipped. The optional trend checkbox separately requires the minutes 1–10 regression to point in the same direction. Prices are selected from the actual corresponding Up/Down token, never inferred from the other side.

The bid slider sets the total debit including modeled fees, from $10 to $1,000. After-cost scenarios assume 0.5 cents/share half-spread, 0.5 cents/share slippage and sufficient liquidity. Observations over 90 seconds old and unsupported fee data are excluded. These assumptions do not establish executable historical fills.

The **daily income estimate** is the historical scenario net result divided by all 20 development calendar days, including zero-trade days. Best/worst days and daily CSV exports are available. This is not a future-income forecast. Missing observations and market changes limit its interpretation. Increasing the bid scales modeled returns without establishing that larger fills were available.

The comparison scoreboard ranks rules with at least 60 trades first, then by win percentage, and includes sample size, a descriptive confidence bound and modeled ROI. Trying many settings can overfit the same development sample. The original 192-rule research report and frozen validation decision are preserved; this interactive lab does not rerun validation. Comparison history is session-only unless exported.

## Download all collected CSV data

`all-data-csv.zip` contains nine CSV tables: the eight original collected/research tables plus **bitcoin_reference_samples.csv**, which exports 145,939 actual finer-resolution samples from the retained historical chart responses. Source hashes are included. Missing observations are not filled. The ZIP includes a table guide. Interactive Strategy Lab session results have separate download buttons and do not overwrite the original research tables.

## Updating an existing installation without downloading the data again

The small `dashboard-update.zip` in this folder contains only `app.py` and update instructions. Close the black launcher window, extract that small ZIP, and copy its `app.py` into your existing `polymarket_backtester` folder, replacing the old file. Then double-click `RunDashboard.bat` again. Your existing data stays in place.

Alternatively, use PowerShell:

Close the dashboard launcher window. In File Explorer, open this `polymarket_backtester` folder, type `powershell` in its address bar, and press Enter. Run the following commands to replace only the dashboard file, then restart it:

```powershell
$ErrorActionPreference = 'Stop'
Invoke-WebRequest 'https://raw.githubusercontent.com/evanbeckerman/sellin_wheels/refs/heads/codex/bitcoin-backtester/polymarket_backtester/app.py' -OutFile app.updated.py
Move-Item app.updated.py app.py -Force
.\RunDashboard.bat
```

The saved data, research engine, frozen experiment and validation results are unchanged. The updated dashboard displays one view at a time and performs the slow full-file verification only if requested under Data quality.

See [RESULTS.md](RESULTS.md) for findings, [RESEARCH_DETAILS.md](RESEARCH_DETAILS.md) for methodology, and [docs/sources.md](docs/sources.md) for source verification. The supplied study remains frozen; the launcher does not fetch new market data, retune strategies or alter the validation decision.
