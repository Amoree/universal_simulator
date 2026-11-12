from __future__ import annotations

import re
from typing import Any

FIELDS: dict[str, tuple[str, list[str]]] = {
    "users": ("users", [r"(?:up to|around|about|approximately)?\s*([\d,.]+)\s*(?:users|customers|accounts)\b"]),
    "daily_events": ("events/day", [r"([\d,.]+)\s*(?:events|requests)\s*(?:per|a)\s*day\b", r"([\d,.]+)\s*daily\s*(?:events|requests)\b"]),
    "retention_days": ("days", [r"(?:retain|retention(?:\s+of)?|keep(?:\s+data)?\s+for)\s*(?:up to\s*)?([\d,.]+)\s*days?\b", r"([\d,.]+)\s*days?\s*(?:of\s*)?retention\b"]),
    "peak_factor": ("x", [r"([\d.]+)\s*x\s*(?:peak|traffic|normal)", r"peak(?:\s+traffic)?\s*(?:factor|multiplier)?\s*(?:of|is|:|=)?\s*([\d.]+)"]),
    "budget": ("USD/month", [r"\$\s*([\d,.]+)\s*(?:per\s*month|/\s*month|monthly)?", r"(?:monthly\s+)?budget\s*(?:of|is|:|=)?\s*\$?\s*([\d,.]+)"]),
    "avg_event_size_kb": ("KB", [r"(?:average|avg)\s*(?:event|payload)\s*size\s*(?:of|is|:|=)?\s*([\d.]+)\s*(kb|mb|bytes?)\b"]),
    "response_time_ms": ("ms", [r"(?:response time|latency)\s*(?:of|under|below|less than|target(?: of)?)?\s*([\d,.]+)\s*(ms|milliseconds|s|seconds)\b"]),
    "launch_weeks": ("weeks", [r"(?:launch|ship|deliver)\s*(?:in|within)\s*([\d.]+)\s*weeks?\b"]),
}


def extract_requirements(text: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    lowered = text.lower()
    for key, (unit, patterns) in FIELDS.items():
        for pattern in patterns:
            m = re.search(pattern, text, flags=re.IGNORECASE)
            if not m:
                continue
            value = m.group(1).replace(",", "")
            numeric = float(value) if "." in value else int(value)
            if key == "avg_event_size_kb" and len(m.groups()) > 1:
                if m.group(2).lower() == "mb":
                    numeric = float(numeric) * 1024
                elif m.group(2).lower().startswith("byte"):
                    numeric = float(numeric) / 1024
            if key == "response_time_ms" and len(m.groups()) > 1 and m.group(2).lower() in {"s", "seconds"}:
                numeric = float(numeric) * 1000
            matches.append({
                "category": "system",
                "key": key,
                "value": str(numeric),
                "unit": unit,
                "source_text": m.group(0),
                "confidence": "medium",
                "confirmed": False,
            })
            break
    if not matches and lowered.strip():
        matches.append({
            "category": "system",
            "key": "description",
            "value": text,
            "unit": None,
            "source_text": text,
            "confidence": "low",
            "confirmed": False,
        })
    return matches


def simulate(requirements: list[dict[str, Any]], overrides: dict[str, float] | None = None) -> dict[str, Any]:
    values: dict[str, float] = {}
    for req in requirements:
        try:
            values[req["key"]] = float(str(req.get("value", "")).replace(",", "").strip())
        except (TypeError, ValueError):
            continue
    values.update(overrides or {})

    warnings: list[str] = []
    assumptions: list[str] = []

    daily_events = values.get("daily_events")
    peak_factor = values.get("peak_factor")
    avg_rps = daily_events / 86400 if daily_events is not None else None
    peak_rps = avg_rps * peak_factor if avg_rps is not None and peak_factor is not None else None

    if daily_events is None:
        warnings.append("Daily request/event volume is missing; workload cannot be estimated.")
    if peak_factor is None:
        warnings.append("Peak traffic factor is missing; only average requests per second is estimated.")
    if peak_factor is not None:
        assumptions.append(f"Peak load uses a {peak_factor:g}× traffic multiplier.")

    retention = values.get("retention_days")
    event_size_kb = values.get("avg_event_size_kb")
    storage_gb = None
    if daily_events is not None and retention is not None and event_size_kb is not None:
        storage_gb = daily_events * retention * event_size_kb * 1024 * 1.25 / (1024 ** 3)
        assumptions.append("Storage estimate includes 25% overhead for indexes and metadata; replication and backups are excluded.")
    else:
        missing = [name for name, value in (("daily event volume", daily_events), ("retention period", retention), ("average event size", event_size_kb)) if value is None]
        if missing:
            warnings.append("Storage estimate needs: " + ", ".join(missing) + ".")

    budget = values.get("budget")
    if budget is not None:
        assumptions.append(f"Monthly budget constraint is set to ${budget:g}.")

    summary = " ".join([
        f"Average workload: {avg_rps:.3f} rps." if avg_rps is not None else "Average workload unavailable.",
        f"Peak workload: {peak_rps:.3f} rps." if peak_rps is not None else "Peak workload unavailable.",
        f"Estimated retained data: {storage_gb:.2f} GB." if storage_gb is not None else "Storage estimate unavailable.",
    ])

    return {
        "summary": summary,
        "average_rps": round(avg_rps, 4) if avg_rps is not None else None,
        "peak_rps": round(peak_rps, 4) if peak_rps is not None else None,
        "storage_gb": round(storage_gb, 3) if storage_gb is not None else None,
        "monthly_budget_usd": budget,
        "warnings": warnings,
        "assumptions": assumptions,
    }
