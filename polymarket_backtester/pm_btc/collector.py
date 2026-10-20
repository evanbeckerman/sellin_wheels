import csv
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from .normalize import contract_target, finite_number, historical_observations, normalize_market
from .transport import PublicHTTP, SourceError
from .reference import fetch_reference
from .window import Window, iso

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DATA = "https://data-api.polymarket.com"

MARKET_FIELDS = ["slug", "start_ts", "start_utc", "end_utc", "split", "discovery_status", "market_id",
    "condition_id", "question", "up_token_id", "down_token_id", "closed", "resolution_status",
    "winning_outcome", "winner_source", "resolution_source", "rules", "rules_status", "reference_method", "opening_price",
    "settlement_price", "settlement_check", "reference_value_source", "aggregate_liquidity_metadata",
    "fee_metadata_json", "historical_fee_verified", "source_sha256", "error"]
REFERENCE_FIELDS = ["slug", "minute", "target_ts", "target_utc", "price", "reference_type", "status", "source_sha256"]
HISTORY_FIELDS = ["slug", "outcome", "token_id", "timestamp", "time_utc", "price", "price_type", "source_sha256"]
TARGET_FIELDS = ["slug", "outcome", "minute", "target_ts", "target_utc", "token_id", "exact_history_price",
    "history_status", "last_observation_price", "last_observation_ts", "last_observation_age_seconds",
    "historical_bid", "historical_ask", "historical_ask_size", "historical_depth_usd", "execution_status",
    "source_sha256", "exact_trade_price", "last_trade_price", "last_trade_ts", "last_trade_age_seconds",
    "last_trade_side", "last_trade_size", "trade_source_sha256"]
TRADE_FIELDS = ["slug", "token_id", "outcome", "timestamp", "price", "size", "side", "transaction_hash", "source_sha256"]
ISSUE_FIELDS = ["slug", "component", "category", "detail"]


def write_csv(path, rows, fields):
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", newline="") as out:
        writer = csv.DictWriter(out, fields, extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    temp.replace(path)


def write_json(path, payload):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, allow_nan=False))
    temp.replace(path)


def expected_market(start, window, status="not_requested", error=""):
    return {"slug": f"btc-updown-15m-{start}", "start_ts": start, "start_utc": iso(start),
            "end_utc": iso(start + 900), "split": window.split(start), "discovery_status": status,
            "historical_fee_verified": False, "error": error}


def reference_rows(market):
    for minute in range(16):
        value = market.get("opening_price") if minute == 0 else market.get("settlement_price") if minute == 15 else None
        yield {"slug": market["slug"], "minute": minute,
               "target_ts": market["start_ts"] + minute * 60, "target_utc": iso(market["start_ts"] + minute * 60),
               "price": value, "reference_type": market.get("reference_method", "") if value is not None else "",
               "status": "reported_event_metadata_not_independent_tape" if value is not None else "missing_verified_reference_observation",
               "source_sha256": market.get("source_sha256", "") if value is not None else ""}


def collect_trades(http, market, issues):
    """Actual prints only; a print's size/side is never treated as available liquidity."""
    rows, seen = [], set()
    complete = False
    if not market.get("condition_id"):
        return rows, complete
    for offset in range(0, 10000, 500):
        try:
            payload, receipt = http.get(DATA + "/trades", {"market": market["condition_id"], "limit": 500, "offset": offset})
            if not isinstance(payload, list):
                raise ValueError("Expected a trade array")
            # Filter both condition AND token: never mix events or opposite tokens.
            for item in payload:
                if item.get("conditionId") != market["condition_id"]:
                    raise ValueError("Trade response contains a different conditionId")
                token = str(item.get("asset", ""))
                token_outcomes = {market["up_token_id"]: "Up", market["down_token_id"]: "Down"}
                if token not in token_outcomes:
                    raise ValueError("Trade response contains an unknown token")
                timestamp = finite_number(item.get("timestamp"))
                price = finite_number(item.get("price"), 0, 1)
                size = finite_number(item.get("size"), 0)
                if timestamp is None or timestamp != int(timestamp) or price is None or size is None:
                    raise ValueError("Malformed historical trade")
                timestamp = int(timestamp)
                if not market["start_ts"] <= timestamp <= market["start_ts"] + 900:
                    continue
                row = {"slug": market["slug"], "token_id": token, "outcome": token_outcomes[token],
                       "timestamp": timestamp, "price": price, "size": size, "side": item.get("side", ""),
                       "transaction_hash": item.get("transactionHash", ""), "source_sha256": receipt["sha256"]}
                identity = tuple(row[k] for k in ("token_id", "timestamp", "price", "size", "side", "transaction_hash"))
                if identity not in seen:
                    rows.append(row)
                    seen.add(identity)
            if len(payload) < 500:
                complete = True
                break
        except (SourceError, ValueError, KeyError, TypeError) as exc:
            issues.append({"slug": market["slug"], "component": "trades", "category": getattr(exc, "category", "schema_error"), "detail": str(exc)})
            break
    if not complete:
        issues.append({"slug": market["slug"], "component": "trades", "category": "incomplete_trade_history",
                       "detail": "Pagination cap or source failure: this trade tape is not proven complete"})
    return sorted(rows, key=lambda x: x["timestamp"]), complete


def add_trade_evidence(target, trades):
    prior = [t for t in trades if t["outcome"] == target["outcome"] and t["timestamp"] <= target["target_ts"]]
    if prior:
        last = prior[-1]
        target.update(last_trade_price=last["price"], last_trade_ts=last["timestamp"],
                      last_trade_age_seconds=target["target_ts"] - last["timestamp"],
                      last_trade_side=last["side"], last_trade_size=last["size"], trade_source_sha256=last["source_sha256"])
        # Multiple executions at the exact second can have different prices: do not invent a single exact price.
        exact = {t["price"] for t in prior if t["timestamp"] == target["target_ts"]}
        if len(exact) == 1:
            target["exact_trade_price"] = exact.pop()


def collect(window: Window, root: Path, max_markets=None, with_trades=True, http=None, progress=print, workers=24):
    directory = Path(root) / window.key
    directory.mkdir(parents=True, exist_ok=True)
    owns_http = http is None
    http = http or PublicHTTP(directory)
    expected = window.slots
    selected = expected[:max_markets] if max_markets is not None else expected
    markets = {s: expected_market(s, window) for s in expected}
    history, targets, trades, issues = [], [], [], []
    official_references = {}
    verified_paths = set()
    probe = {}
    historical_contract_endpoint_verified = False
    # Check actual public APIs. A successful root/health check is never counted as historical-data availability.
    for name, url, params in [
        ("gamma", GAMMA + "/events", {"slug": f"btc-updown-15m-{selected[0]}"}),
        ("clob", CLOB + "/", None), ("data_api", DATA + "/trades", {"limit": 1})]:
        try:
            payload, receipt = http.get(url, params, refresh=True)
            if name in {"gamma", "data_api"} and not isinstance(payload, list):
                raise ValueError("Unexpected API response schema")
            probe[name] = {"status": "reachable", "sha256": receipt["sha256"]}
        except (SourceError, ValueError) as exc:
            probe[name] = {"status": "failed", "category": getattr(exc, "category", "schema_error"), "detail": str(exc)}
            issues.append({"slug": "", "component": name, "category": probe[name]["category"], "detail": str(exc)})
    if probe["gamma"]["status"] != "reachable":
        for start in selected:
            markets[start] = expected_market(start, window, "blocked", probe["gamma"]["detail"])
    else:
        # Gamma supports repeated slug filters. Validate every returned slug before accepting it.
        # Reject duplicate/foreign results; a bad schema must not be mistaken for an empty interval.
        for index in range(0, len(selected), 50):
            batch = selected[index:index + 50]
            requested = {f"btc-updown-15m-{s}": s for s in batch}
            try:
                events, receipt = http.get(GAMMA + "/events", [("slug", slug) for slug in requested] + [("limit", len(batch))])
                if not isinstance(events, list):
                    raise ValueError("Gamma response must be an event array")
                received = [e.get("slug") for e in events]
                if len(received) != len(set(received)) or any(s not in requested for s in received):
                    raise ValueError("Gamma response has duplicate or unrequested slugs")
                by_slug = {e["slug"]: e for e in events}
                for slug, start in requested.items():
                    if slug not in by_slug:
                        markets[start] = expected_market(start, window, "not_returned")
                        continue
                    try:
                        row = normalize_market(by_slug[slug], start, window.split(start))
                        row["source_sha256"] = receipt["sha256"]
                        markets[start] = row
                    except (ValueError, KeyError, TypeError) as exc:
                        markets[start] = expected_market(start, window, "invalid_source_record", str(exc))
                        issues.append({"slug": slug, "component": "metadata", "category": "schema_error", "detail": str(exc)})
            except (SourceError, ValueError, KeyError, TypeError) as exc:
                for start in batch:
                    markets[start] = expected_market(start, window, "source_error", str(exc))
                issues.append({"slug": "", "component": "gamma_batch", "category": getattr(exc, "category", "schema_error"), "detail": str(exc)})
                if isinstance(exc, SourceError) and exc.category in {"network_policy_denied", "http_403", "http_401"}:
                    for start in selected[index + len(batch):]:
                        markets[start] = expected_market(start, window, "blocked", str(exc))
                    break
            progress(f"Discovered metadata for {min(index + 50, len(selected))}/{len(selected)} requested intervals")
        def collect_one(start):
            row = markets[start]
            local_issues, local_history, local_targets = [], [], []
            refs, reference_verified = None, False
            try:
                refs, reference_verified = fetch_reference(http, row)
                if not reference_verified:
                    local_issues.append({"slug": row["slug"], "component": "bitcoin_reference", "category": "incomplete_reference_path",
                                         "detail": "Missing exact minute observations or endpoint cross-checks; no prices are filled in"})
            except (SourceError, ValueError, KeyError, TypeError) as exc:
                local_issues.append({"slug": row["slug"], "component": "bitcoin_reference", "category": getattr(exc, "category", "reference_validation_error"), "detail": str(exc)})
            observations_by_outcome = {"Up": [], "Down": []}
            for outcome in ("Up", "Down"):
                if probe["clob"]["status"] != "reachable":
                    continue
                token = row[f"{outcome.lower()}_token_id"]
                try:
                    payload, receipt = http.get(CLOB + "/prices-history", {"market": token, "startTs": start, "endTs": start + 900, "fidelity": 1})
                    observations = historical_observations(payload, token, start, start + 900, receipt["sha256"])
                    # Successful but empty history proves no usable availability for this token.
                    observations_by_outcome[outcome] = observations
                    for observation in observations:
                        local_history.append({"slug": row["slug"], "outcome": outcome, **observation})
                    if not observations:
                        local_issues.append({"slug": row["slug"], "component": f"{outcome}_history", "category": "empty_history", "detail": "Endpoint returned no observations for this historical interval"})
                except (SourceError, ValueError, KeyError, TypeError) as exc:
                    local_issues.append({"slug": row["slug"], "component": f"{outcome}_history", "category": getattr(exc, "category", "schema_error"), "detail": str(exc)})
            market_trades = []
            # Trade prints are an alternative source when chart histories are missing.
            if with_trades and not all(observations_by_outcome.values()) and probe["data_api"]["status"] == "reachable":
                market_trades, _ = collect_trades(http, row, local_issues)
            for outcome in ("Up", "Down"):
                for minute in (10, 11, 12, 13):
                    target = contract_target(observations_by_outcome[outcome], row, outcome, minute)
                    add_trade_evidence(target, market_trades)
                    local_targets.append(target)
            return start, local_history, local_targets, market_trades, local_issues, refs, reference_verified
        found_starts = [s for s in selected if markets[s]["discovery_status"] == "found"]
        # Workers overlap network latency; PublicHTTP caps total request starts at 20/second.
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(collect_one, start) for start in found_starts]
            for count, future in enumerate(as_completed(futures), 1):
                start, hs, ts, prints, problems, refs, verified = future.result()
                history.extend(hs)
                targets.extend(ts)
                trades.extend(prints)
                issues.extend(problems)
                historical_contract_endpoint_verified |= bool(hs)
                if refs is not None:
                    official_references[markets[start]["slug"]] = refs
                if verified:
                    verified_paths.add(markets[start]["slug"])
                if count % 100 == 0 or count == len(found_starts):
                    progress(f"Collected reference/contract evidence for {count}/{len(found_starts)} markets; validated 1–10 minute reference paths: {len(verified_paths)}")
    # Include every expected interval, even when no actual source record was downloadable.
    have_targets = {t["slug"] for t in targets}
    for market in markets.values():
        if market["slug"] not in have_targets:
            for outcome in ("Up", "Down"):
                for minute in (10, 11, 12, 13):
                    targets.append(contract_target([], market, outcome, minute))
    references = [r for m in markets.values() for r in official_references.get(m["slug"], list(reference_rows(m)))]
    records = list(markets.values())
    targets.sort(key=lambda r: (r["target_ts"], r["outcome"]))
    history.sort(key=lambda r: (r["slug"], r["outcome"], r["timestamp"]))
    trades.sort(key=lambda r: (r["slug"], r["token_id"], r["timestamp"], r["transaction_hash"], r["price"], r["size"]))
    issues.sort(key=lambda r: (r["slug"], r["component"], r["category"], r["detail"]))
    for filename, data, fields in [("markets.csv", records, MARKET_FIELDS),
                                  ("reference_minutes.csv", references, REFERENCE_FIELDS),
                                  ("contract_history.csv", history, HISTORY_FIELDS),
                                  ("contract_targets.csv", targets, TARGET_FIELDS),
                                  ("trades.csv", trades, TRADE_FIELDS), ("issues.csv", issues, ISSUE_FIELDS)]:
        write_csv(directory / filename, data, fields)
    found = [m for m in records if m["discovery_status"] == "found"]
    audit = {
        "generated_at": datetime.now(timezone.utc).isoformat(), "dataset_directory": str(directory),
        "start_date_inclusive": str(window.start_date), "end_date_exclusive": str(window.end_date),
        "timezone": window.timezone_name, "start_utc": iso(window.start_ts), "end_utc": iso(window.end_ts),
        "expected_intervals": len(expected), "requested_intervals": len(selected),
        "actual_markets_downloaded": len(found), "resolved_winners": sum(bool(m.get("winning_outcome")) for m in found),
        "rule_patterns_verified": sum(m.get("rules_status") == "chainlink_btc_usd_ties_up" for m in found),
        "settlement_mismatches": sum(m.get("settlement_check") == "MISMATCH" for m in found),
        "reference_samples_available": sum(r["price"] is not None for r in references),
        "reference_samples_required": len(expected) * 16,
        "complete_reference_paths": sum(all(r["price"] is not None for r in official_references.get(s, [])) and len(official_references.get(s, [])) == 16 for s in verified_paths),
        "validated_trend_reference_paths": len(verified_paths),
        "analysis_eligible_slugs": sorted(s for s in verified_paths if next(m for m in records if m["slug"] == s).get("settlement_check") == "consistent"),
        "contract_history_observations": len(history), "actual_trade_prints": len(trades),
        "exact_entry_history_observations": sum(t["exact_history_price"] is not None for t in targets),
        "entry_observations_required": len(expected) * 8, "historical_orderbook_snapshots": 0,
        "verified_historical_fee_schedules": 0, "historical_contract_endpoint_verified": historical_contract_endpoint_verified,
        "api_probes": probe, "analysis_ready": len(verified_paths) == len(expected) and all(m.get("settlement_check") == "consistent" for m in records), "execution_backtest_ready": False,
        "collection_complete": len(verified_paths) == len(expected) and all(r["price"] is not None for r in references) and all(t["exact_history_price"] is not None for t in targets),
        "status": "network_blocked" if any(p.get("category") == "network_policy_denied" for p in probe.values()) else "incomplete",
        "development_validation_split": "first 20 / final 10 complete local days" if window.days == 30 else "diagnostic run only",
        "limitations": [
            "Expected intervals are a checklist, not fabricated market records.",
            "Only exact official chart observations with matching market-metadata endpoints qualify as verified reference paths. Missing intervals remain excluded; no other BTC exchange is substituted.",
            "Reported Gamma opening/settlement metadata, when present, is retained separately from an independently verified reference tape.",
            "Historical CLOB observations and executed trades are not executable asks or order-book depth.",
            "A current fee-rate or live orderbook cannot establish historical fees or execution costs.",
            "Incomplete-window analysis must disclose excluded intervals. Executable profitability is unverified without historical asks, depth and fee evidence.",
        ],
    }
    files = {}
    for filename in ("markets.csv", "reference_minutes.csv", "contract_history.csv", "contract_targets.csv", "trades.csv", "issues.csv"):
        path = directory / filename
        files[filename] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
    audit["files"] = files
    write_json(directory / "audit.json", audit)
    if owns_http:
        http.close()
    progress(json.dumps({k: audit[k] for k in ("status", "actual_markets_downloaded", "expected_intervals", "contract_history_observations", "reference_samples_available")}, indent=2))
    return audit


def verify_artifacts(directory):
    directory = Path(directory)
    audit = json.loads((directory / "audit.json").read_text())
    failures = []
    for name, receipt in audit["files"].items():
        path = directory / name
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != receipt["sha256"]:
            failures.append(f"CSV integrity failure: {name}")
    for path in (directory / "raw").glob("*.receipt.json"):
        receipt = json.loads(path.read_text())
        body = directory / "raw" / receipt["body_file"]
        if not body.exists() or hashlib.sha256(body.read_bytes()).hexdigest() != receipt["sha256"]:
            failures.append(f"Source integrity failure: {path.name}")
    return failures
