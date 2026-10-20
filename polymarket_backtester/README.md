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

- **Data quality:** See what was collected and what is missing.
- **Market explorer:** Inspect real markets and the first-10-minute regression.
- **Trend analysis:** Compare predictions with settlements.
- **Development strategies:** Adjust thresholds using development data only. Strict mode requires historical asks/depth, which this dataset lacks; turn it off only to inspect the clearly labeled assumed-execution scenarios.
- **Frozen validation:** See why no optimized trading rule passed the prespecified screen.

The baseline predicted the final direction correctly in **613 of 810 usable validation markets (75.68%)**. That does **not** demonstrate profitable trading. Missing historical reference prices and historical order-book data are disclosed. Do not trade on these results.

See [RESULTS.md](RESULTS.md) for findings, [RESEARCH_DETAILS.md](RESEARCH_DETAILS.md) for methodology, and [docs/sources.md](docs/sources.md) for source verification. The supplied study remains frozen; the launcher does not fetch new market data, retune strategies or alter the validation decision.
