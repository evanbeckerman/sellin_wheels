"""Conservative normalization: unknown values stay unknown; no price interpolation."""
import json
import math
from datetime import datetime
from decimal import Decimal, InvalidOperation

from .window import iso


def array(value):
    result = json.loads(value) if isinstance(value, str) else value
    if not isinstance(result, list):
        raise ValueError("Expected an array")
    return result


def finite_number(value, low=None, high=None):
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    if not math.isfinite(result) or (low is not None and result < low) or (high is not None and result > high):
        return None
    return result


def normalize_market(event, start, split):
    slug = f"btc-updown-15m-{start}"
    if event.get("slug") != slug:
        raise ValueError("Response slug does not match requested interval")
    candidates = [m for m in event.get("markets", []) if m.get("slug") == slug]
    if len(candidates) != 1:
        raise ValueError("Expected exactly one matching 15-minute market")
    market = candidates[0]
    title = str(market.get("question", event.get("title", "")))
    if "bitcoin" not in title.lower() and "btc" not in title.lower():
        raise ValueError("Market question is not Bitcoin")
    end = datetime.fromisoformat(market["endDate"].replace("Z", "+00:00"))
    if end.tzinfo is None or int(end.timestamp()) != start + 900:
        raise ValueError("Market endDate disagrees with requested 15-minute interval")
    if market.get("eventStartTime"):
        declared_start = datetime.fromisoformat(market["eventStartTime"].replace("Z", "+00:00"))
        if declared_start.tzinfo is None or int(declared_start.timestamp()) != start:
            raise ValueError("Market eventStartTime disagrees with slug timestamp")
    outcomes, tokens = array(market["outcomes"]), array(market["clobTokenIds"])
    if len(tokens) != 2 or len(outcomes) != 2 or set(outcomes) != {"Up", "Down"}:
        raise ValueError("Expected distinct Up and Down tokens")
    if not all(str(t).isdecimal() for t in tokens) or len(set(map(str, tokens))) != 2:
        raise ValueError("Malformed or duplicate CLOB token identifiers")
    token_by_outcome = dict(zip(outcomes, map(str, tokens)))
    description = str(market.get("description", event.get("description", "")))
    source = str(market.get("resolutionSource", event.get("resolutionSource", "")))
    text = (description + " " + source).lower()
    chainlink = "chainlink" in text or "data.chain.link" in text
    stream = "btc-usd" in text or "btc/usd" in text
    ties_up = ("greater than or equal to" in text or "higher than or equal to" in text)
    # This is a rule-pattern check, not a claim that a reference tape was validated.
    rules_status = "chainlink_btc_usd_ties_up" if chainlink and stream and ties_up else "manual_review_required"
    reference_method = "unknown"
    if rules_status != "manual_review_required":
        config = market.get("cryptoMarketConfig") or {}
        if "twap" in text and "btc-usd-twap-60s" in source and config.get("twapEnabled") is True and config.get("twapLookbackSeconds") == 60:
            reference_method = "chainlink_btc_usd_twap_60s"
        elif "twap" not in text:
            reference_method = "chainlink_btc_usd_spot"
        else:
            rules_status = "manual_review_required"
    winner = ""
    if market.get("closed") is True and market.get("umaResolutionStatus") == "resolved":
        try:
            prices = [Decimal(str(p)) for p in array(market["outcomePrices"])]
            if sorted(prices) == [Decimal(0), Decimal(1)]:
                winner = outcomes[prices.index(Decimal(1))]
        except (KeyError, ValueError, InvalidOperation):
            pass
    # Event metadata can supply actual opening/closing values, but only for verified rule patterns.
    metadata = event.get("eventMetadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    opening = finite_number(metadata.get("priceToBeat"), low=0)
    closing = finite_number(metadata.get("finalPrice"), low=0) if winner else None
    if rules_status != "chainlink_btc_usd_ties_up":
        opening = closing = None
    if opening == 0:
        opening = None
    if closing == 0:
        closing = None
    settlement_check = "not_checkable"
    if opening is not None and closing is not None and winner:
        settlement_check = "consistent" if ("Up" if closing >= opening else "Down") == winner else "MISMATCH"
    return {
        "slug": slug, "start_ts": start, "start_utc": iso(start), "end_utc": iso(start + 900),
        "split": split, "discovery_status": "found", "market_id": str(market.get("id", "")),
        "condition_id": market.get("conditionId", ""), "question": title,
        "up_token_id": token_by_outcome["Up"], "down_token_id": token_by_outcome["Down"],
        "closed": market.get("closed"), "resolution_status": market.get("umaResolutionStatus", ""),
        "winning_outcome": winner, "winner_source": "gamma_resolved_outcomePrices" if winner else "",
        "resolution_source": source, "rules": description, "rules_status": rules_status,
        "reference_method": reference_method,
        "opening_price": opening, "settlement_price": closing, "settlement_check": settlement_check,
        "reference_value_source": "gamma.eventMetadata" if opening is not None or closing is not None else "",
        # Aggregate market liquidity is NOT a historical entry-time book snapshot.
        "aggregate_liquidity_metadata": market.get("liquidity", ""),
        "fee_metadata_json": json.dumps({k: market[k] for k in
            ("feesEnabled", "feeType", "makerBaseFee", "takerBaseFee", "feeSchedule") if k in market}),
        "historical_fee_verified": False, "error": "",
    }


def historical_observations(payload, token, start, end, source_hash):
    if not isinstance(payload, dict) or not isinstance(payload.get("history"), list):
        raise ValueError("CLOB prices-history response must contain a history array")
    rows, seen = [], {}
    for item in payload["history"]:
        timestamp = finite_number(item.get("t"))
        price = finite_number(item.get("p"), low=0, high=1)
        if timestamp is None or timestamp != int(timestamp) or price is None:
            raise ValueError("Malformed historical price observation")
        timestamp = int(timestamp)
        if timestamp < start or timestamp > end:
            continue
        if timestamp in seen:
            if seen[timestamp] != price:
                raise ValueError("Conflicting history observations at one timestamp")
            continue
        seen[timestamp] = price
        rows.append({"token_id": token, "timestamp": timestamp, "time_utc": iso(timestamp),
                     "price": price, "price_type": "clob_history_observation_not_executable_ask",
                     "source_sha256": source_hash})
    return sorted(rows, key=lambda x: x["timestamp"])


def contract_target(observations, market, outcome, minute):
    target = market["start_ts"] + minute * 60
    previous = [o for o in observations if o["timestamp"] <= target]
    last = previous[-1] if previous else None
    exact = last if last and last["timestamp"] == target else None
    return {
        "slug": market["slug"], "outcome": outcome, "minute": minute, "target_ts": target,
        "target_utc": iso(target), "token_id": market.get(f"{outcome.lower()}_token_id", ""),
        "exact_history_price": exact["price"] if exact else None,
        "history_status": "exact_observation" if exact else "missing_exact_observation",
        "last_observation_price": last["price"] if last else None,
        "last_observation_ts": last["timestamp"] if last else None,
        "last_observation_age_seconds": target - last["timestamp"] if last else None,
        "historical_bid": None, "historical_ask": None, "historical_ask_size": None,
        "historical_depth_usd": None, "execution_status": "historical_orderbook_unavailable",
        "source_sha256": last["source_sha256"] if last else "",
    }
