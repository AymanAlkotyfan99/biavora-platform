from __future__ import annotations


def infer_chart_type_from_shape(*, columns: list[str], rows: list[dict], intent: dict | None = None) -> tuple[str, str]:
    lower_cols = [str(c or "").strip().lower() for c in (columns or [])]
    numeric = []
    if rows and isinstance(rows[0], dict):
        sample = rows[:25]
        for col in columns:
            vals = [r.get(col) for r in sample if isinstance(r, dict) and r.get(col) is not None]
            if vals and all(isinstance(v, (int, float)) for v in vals):
                numeric.append(col)
    time_like = [c for c in lower_cols if any(t in c for t in ("period", "date", "ds", "month", "week", "year", "timestamp", "time"))]
    geo_like = [c for c in lower_cols if any(t in c for t in ("country", "city", "region", "location"))]
    intent_text = str((intent or {}).get("intent") or (intent or {}).get("intent_type") or "").lower()
    if time_like and numeric:
        return "line", "time_metric_shape"
    if "correlation" in intent_text and len(numeric) >= 2:
        return "scatter", "correlation_intent"
    if geo_like and numeric:
        return "map", "geo_shape"
    if any("share" in c or "percent" in c for c in lower_cols) and numeric:
        return "pie", "share_metric"
    if len(lower_cols) >= 2 and numeric:
        return "bar", "category_metric_shape"
    return "table", "no_structured_shape"
