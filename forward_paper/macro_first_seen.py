"""Causal macro first-seen handling for the ETH forward paper study.

No network client lives here. Callers must persist the actual read time from the
connected source. Historical release_at is metadata only and can never be used as
our own first_seen timestamp.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import datetime, timezone

EXPECTED = {
    "cpi_yoy": "30771871",
    "core_cpi_mom": "30771844",
    "nfp": "30771890",
    "unemployment": "30771865",
    "core_pce_yoy": "30771724",
    "ppi_yoy": "30771924",
    "fed_funds_target": "30771885",
}


def _dt(value: str) -> datetime:
    t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("Timezone required")
    return t.astimezone(timezone.utc)


def _num(value):
    if value is None:
        return None
    x = float(value)
    if not math.isfinite(x):
        raise ValueError("Non-finite macro value")
    return x


def _sign(actual, forecast) -> str:
    if actual is None or forecast is None:
        return "no_forecast"
    d = actual - forecast
    return "positive" if d > 0 else ("negative" if d < 0 else "inline")


def _next_full_hour(t: datetime) -> str:
    # Deliberately strictly after first_seen, even if first_seen is on the hour.
    floor = t.replace(minute=0, second=0, microsecond=0)
    return (floor + __import__("datetime").timedelta(hours=1)).isoformat()


def _event_id(indicator_code: str, period: str, release_at: str) -> str:
    raw = f"{indicator_code}|{period}|{release_at}".encode()
    return hashlib.sha256(raw).hexdigest()[:24]


def normalize_capture(capture: dict, *, max_forward_lag_minutes: float = 90.0) -> dict:
    if max_forward_lag_minutes <= 0:
        raise ValueError("Invalid macro lag threshold")
    if capture.get("schema") != "macro-first-seen-capture-v1":
        raise ValueError("Unexpected macro capture schema")
    first_seen = _dt(capture["batch_first_seen_at_utc"])
    rows = capture.get("indicators")
    if not isinstance(rows, list) or len(rows) != len(EXPECTED):
        raise ValueError("Capture must cover all seven frozen macro indicators")

    seen = set()
    events = []
    empty = []
    for item in rows:
        indicator = item.get("indicator")
        code = item.get("indicator_code")
        if indicator not in EXPECTED or EXPECTED[indicator] != code or indicator in seen:
            raise ValueError("Unexpected/duplicate macro indicator mapping")
        seen.add(indicator)
        count = int(item.get("count", -1))
        if count < 0:
            raise ValueError("Invalid macro row count")
        latest = item.get("latest")
        if count == 0:
            if latest is not None:
                raise ValueError("Zero-count source cannot contain a latest row")
            empty.append({
                "indicator": indicator,
                "indicator_code": code,
                "checked_at_utc": first_seen.isoformat(),
                "status": "no_row_in_query_window",
                "forward_interpretation": "unknown_not_no_event",
            })
            continue
        if not isinstance(latest, dict):
            raise ValueError("Non-empty source requires latest row")
        release = _dt(latest["release_at"])
        if release > first_seen:
            raise ValueError("Macro release timestamp is in the future relative to first_seen")
        actual = _num(latest.get("actual_value"))
        forecast = _num(latest.get("forecast_value"))
        previous = _num(latest.get("previous_value"))
        if actual is None:
            raise ValueError("Published macro row lacks actual value")
        lag = (first_seen - release).total_seconds() / 60.0
        eligible = lag <= max_forward_lag_minutes
        release_iso = release.isoformat()
        eid = _event_id(code, str(latest["period"]), release_iso)
        events.append({
            "event_id": eid,
            "indicator": indicator,
            "indicator_code": code,
            "indicator_name": item.get("name"),
            "periodicity": item.get("periodicity"),
            "period": str(latest["period"]),
            "release_at_utc": release_iso,
            "first_seen_at_utc": first_seen.isoformat(),
            "actual": actual,
            "forecast": forecast,
            "previous": previous,
            "unit": latest.get("unit"),
            "surprise_raw": None if forecast is None else actual - forecast,
            "sign": _sign(actual, forecast),
            "first_seen_lag_minutes": lag,
            "forward_eligible": eligible,
            "usable_at_utc": _next_full_hour(first_seen) if eligible else None,
            "eligibility_reason": "timely_first_seen" if eligible else "late_bootstrap_observation",
            "source": capture.get("source"),
        })

    if seen != set(EXPECTED):
        raise ValueError("Frozen macro indicator set incomplete")
    return {
        "schema": "macro-first-seen-normalized-v1",
        "capture_first_seen_at_utc": first_seen.isoformat(),
        "max_forward_lag_minutes": float(max_forward_lag_minutes),
        "events": sorted(events, key=lambda x: (x["release_at_utc"], x["indicator"])),
        "empty_indicators": sorted(empty, key=lambda x: x["indicator"]),
        "forward_eligible_event_count": sum(bool(e["forward_eligible"]) for e in events),
        "late_bootstrap_event_count": sum(not bool(e["forward_eligible"]) for e in events),
        "source_set_checked": True,
    }


def merge_ledger(existing: dict | None, normalized: dict) -> dict:
    """Preserve the earliest first-seen values; later changes become revisions."""
    if normalized.get("schema") != "macro-first-seen-normalized-v1":
        raise ValueError("Unexpected normalized schema")
    ledger = copy.deepcopy(existing) if existing else {
        "schema": "macro-first-seen-ledger-v1",
        "events": {},
        "empty_checks": [],
    }
    if ledger.get("schema") != "macro-first-seen-ledger-v1":
        raise ValueError("Unexpected ledger schema")

    for event in normalized["events"]:
        key = event["event_id"]
        if key not in ledger["events"]:
            ledger["events"][key] = {**copy.deepcopy(event), "later_revisions": []}
            continue
        original = ledger["events"][key]
        # A later read may show revisions. Never overwrite the causal first-seen row.
        comparable = ("actual", "forecast", "previous", "unit")
        changed = {k: event.get(k) for k in comparable if event.get(k) != original.get(k)}
        if changed:
            revision = {
                "observed_at_utc": event["first_seen_at_utc"],
                "changed_fields": changed,
            }
            if revision not in original["later_revisions"]:
                original["later_revisions"].append(revision)

    for empty in normalized["empty_indicators"]:
        if empty not in ledger["empty_checks"]:
            ledger["empty_checks"].append(copy.deepcopy(empty))
    return ledger


def digest(obj: dict) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
