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

ARCHITECTURE_KEYS = {
    "database_type": "Database",
    "deployment_region": "Deployment region",
    "cache_enabled": "Cache",
    "queue_enabled": "Background queue",
    "compute_instances": "Application instances",
    "compute_unit_cost": "Monthly cost per application instance",
    "database_monthly_cost": "Monthly database cost",
    "cache_monthly_cost": "Monthly cache cost",
    "queue_monthly_cost": "Monthly queue cost",
    "storage_cost_per_gb": "Storage cost per GB/month",
    "network_monthly_cost": "Monthly networking allowance",
    "availability_target": "Availability target",
}


def extract_requirements(text: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for key, (unit, patterns) in FIELDS.items():
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            raw = match.group(1).replace(",", "")
            value: int | float = float(raw) if "." in raw else int(raw)
            if key == "avg_event_size_kb" and len(match.groups()) > 1:
                size_unit = match.group(2).lower()
                if size_unit == "mb":
                    value = float(value) * 1024
                elif size_unit.startswith("byte"):
                    value = float(value) / 1024
            if key == "response_time_ms" and len(match.groups()) > 1 and match.group(2).lower() in {"s", "seconds"}:
                value = float(value) * 1000
            matches.append({"category": "system", "key": key, "value": str(value), "unit": unit,
                            "source_text": match.group(0), "confidence": "medium", "confirmed": False})
            break
    return matches


def _numeric_requirements(requirements: list[dict[str, Any]], overrides: dict[str, float]) -> dict[str, float]:
    values: dict[str, float] = {}
    for req in requirements:
        try:
            values[req["key"]] = float(str(req.get("value", "")).replace(",", "").strip())
        except (TypeError, ValueError):
            continue
    values.update(overrides or {})
    return values


def simulate(requirements: list[dict[str, Any]], overrides: dict[str, float] | None = None) -> dict[str, Any]:
    """Calculate estimates from explicit user-entered values; never invent missing inputs."""
    values = _numeric_requirements(requirements, overrides or {})
    raw = {item["key"]: str(item.get("value") or "").strip() for item in requirements}
    warnings: list[str] = []
    assumptions: list[str] = []
    architecture: list[str] = []

    daily_events = values.get("daily_events")
    peak_factor = values.get("peak_factor")
    retention = values.get("retention_days")
    event_size_kb = values.get("avg_event_size_kb")
    average_rps = daily_events / 86400 if daily_events is not None else None
    peak_rps = average_rps * peak_factor if average_rps is not None and peak_factor is not None else None

    if daily_events is None:
        warnings.append("Enter daily events or requests to estimate workload.")
    if peak_factor is None:
        warnings.append("Peak traffic factor is missing; peak workload is not estimated.")
    elif peak_factor <= 0:
        warnings.append("Peak traffic factor must be greater than zero.")
    else:
        assumptions.append(f"Peak workload uses your {peak_factor:g}× traffic factor.")

    storage_gb = None
    if daily_events is not None and retention is not None and event_size_kb is not None:
        if min(daily_events, retention, event_size_kb) < 0:
            warnings.append("Traffic, retention, and event size values cannot be negative.")
        else:
            storage_gb = daily_events * retention * event_size_kb / (1024 * 1024) * 1.25
            assumptions.append("Storage includes 25% metadata/index overhead; backups and replicas are excluded.")
    else:
        missing = [label for label, value in (("daily events", daily_events), ("retention days", retention), ("average event size", event_size_kb)) if value is None]
        warnings.append("Storage estimate needs: " + ", ".join(missing) + ".")

    # Explicit, user-provided monthly architecture prices; no provider pricing is assumed.
    compute_count = values.get("compute_instances", 0)
    compute_unit = values.get("compute_unit_cost", 0)
    storage_rate = values.get("storage_cost_per_gb", 0)
    cost_breakdown = {
        "Application compute": max(compute_count, 0) * max(compute_unit, 0),
        "Database": max(values.get("database_monthly_cost", 0), 0),
        "Cache": max(values.get("cache_monthly_cost", 0), 0),
        "Background queue": max(values.get("queue_monthly_cost", 0), 0),
        "Storage": (storage_gb or 0) * max(storage_rate, 0),
        "Networking": max(values.get("network_monthly_cost", 0), 0),
    }
    estimated_cost = round(sum(cost_breakdown.values()), 2)
    has_cost_inputs = any(key in values for key in ("compute_unit_cost", "database_monthly_cost", "cache_monthly_cost", "queue_monthly_cost", "storage_cost_per_gb", "network_monthly_cost"))
    if not has_cost_inputs:
        estimated_cost_result = None
        warnings.append("Estimated infrastructure cost is unavailable until you enter monthly component prices.")
        cost_breakdown_result: dict[str, float] = {}
    else:
        estimated_cost_result = estimated_cost
        cost_breakdown_result = {key: round(value, 2) for key, value in cost_breakdown.items() if value > 0}
        assumptions.append("Cost uses only the monthly component prices and quantities you entered; taxes, support, egress, and discounts may be excluded.")

    budget = values.get("budget")
    budget_remaining = round(budget - estimated_cost, 2) if budget is not None and estimated_cost_result is not None else None
    if budget is not None and budget < 0:
        warnings.append("Monthly budget cannot be negative.")
    if budget_remaining is not None and budget_remaining < 0:
        warnings.append(f"Estimated component cost exceeds the budget by ${abs(budget_remaining):,.2f}/month.")

    for key, label in ARCHITECTURE_KEYS.items():
        value = raw.get(key)
        if value and value.lower() not in {"false", "no", "none", "0"}:
            architecture.append(f"{label}: {value}")

    summary_parts = [
        f"Average workload is {average_rps:,.3f} requests/second." if average_rps is not None else "Workload estimate unavailable.",
        f"Peak workload is {peak_rps:,.3f} requests/second." if peak_rps is not None else "Peak workload estimate unavailable.",
        f"Estimated retained storage is {storage_gb:,.2f} GB." if storage_gb is not None else "Storage estimate unavailable.",
        f"Estimated monthly component cost is ${estimated_cost:,.2f}." if estimated_cost_result is not None else "Infrastructure cost estimate unavailable.",
    ]
    return {
        "summary": " ".join(summary_parts),
        "average_rps": round(average_rps, 4) if average_rps is not None else None,
        "peak_rps": round(peak_rps, 4) if peak_rps is not None else None,
        "storage_gb": round(storage_gb, 3) if storage_gb is not None else None,
        "monthly_budget_usd": budget,
        "estimated_monthly_cost_usd": estimated_cost_result,
        "budget_remaining_usd": budget_remaining,
        "cost_breakdown": cost_breakdown_result,
        "architecture": architecture,
        "warnings": warnings,
        "assumptions": assumptions,
    }
