from __future__ import annotations

import math
import os
import statistics
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

from forecasting.timesfm_service import forecast
from shared.pipeline_guards import (
    forecasting_validator,
    is_technical_column_name,
    time_column_validator,
)


@dataclass
class ForecastRequest:
    requires_forecast: bool
    question_type: str
    reason: str


class ForecastingError(Exception):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


_PREDICTIVE_LABELS = {"predictive", "forecast", "forecasting"}
_EXPLICIT_TIME_PRIORITY = (
    "ds",
    "date",
    "datetime",
    "timestamp",
    "order_date",
    "event_date",
    "created_at",
    "time",
)
_METADATA_TIME_EXACT = {
    "_extracted_at",
    "_cleaned_at",
    "_loaded_at",
    "_batch_id",
    "_processed_at",
    "_ingested_at",
    "_lineage_ts",
}

FORECAST_SERIES_CONFIG = {
    "actual": {
        "series_type": "actual",
        "series_label": "Actual",
        "preferred_color_role": "actual",
        "preferred_color": "#2563eb",
        "stroke_dasharray": "",
    },
    "forecast": {
        "series_type": "forecast",
        "series_label": "Forecast",
        "preferred_color_role": "forecast",
        "preferred_color": "#f97316",
        "stroke_dasharray": "6 4",
    },
}


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def detect_forecast_request(
    *,
    intent: dict[str, Any] | None,
    question_type: str | None = None,
    final_route: str | None = None,
) -> ForecastRequest:
    intent_payload = intent if isinstance(intent, dict) else {}
    normalized_question_type = str(
        question_type
        or intent_payload.get("question_type")
        or intent_payload.get("intent_type")
        or ""
    ).strip().lower()
    requires_forecast_flag = intent_payload.get("requires_forecast")
    route = str(final_route or intent_payload.get("next_step") or "").strip().lower()
    normalized_intent_type = str(intent_payload.get("intent_type", "")).strip().lower()

    if (
        normalized_question_type in _PREDICTIVE_LABELS
        or normalized_intent_type in _PREDICTIVE_LABELS
        or route == "forecasting"
    ):
        return ForecastRequest(
            requires_forecast=True,
            question_type="predictive",
            reason="predictive_invariant",
        )

    if isinstance(requires_forecast_flag, bool):
        return ForecastRequest(
            requires_forecast=requires_forecast_flag,
            question_type=normalized_question_type or "unknown",
            reason="requires_forecast_flag",
        )

    return ForecastRequest(
        requires_forecast=False,
        question_type=normalized_question_type or "unknown",
        reason="not_predictive",
    )


def _is_numeric(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, (int, float, Decimal)):
        try:
            return math.isfinite(float(value))
        except Exception:  # noqa: BLE001
            return False
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return False
        try:
            return math.isfinite(float(normalized))
        except ValueError:
            return False
    return False


def _to_float(value: Any) -> float | None:
    if not _is_numeric(value):
        return None
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is None else value.astimezone(timezone.utc).replace(tzinfo=None)
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if 10**9 <= abs(timestamp) <= 10**12:
            try:
                if abs(timestamp) > 10**11:
                    timestamp = timestamp / 1000.0
                return datetime.utcfromtimestamp(timestamp)
            except Exception:  # noqa: BLE001
                return None
        return None
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        candidate = raw.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed if parsed.tzinfo is None else parsed.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            pass
        formats = (
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M:%S",
            "%m/%d/%Y",
            "%d/%m/%Y",
            "%Y-%m",
        )
        for fmt in formats:
            try:
                parsed = datetime.strptime(raw, fmt)
                if fmt == "%Y-%m":
                    parsed = parsed.replace(day=1)
                return parsed
            except ValueError:
                continue
    return None


def _explicit_time_priority(column: str) -> int:
    lowered = str(column or "").strip().lower()
    if not lowered or lowered in _METADATA_TIME_EXACT:
        return -100
    for idx, preferred in enumerate(_EXPLICIT_TIME_PRIORITY):
        if lowered == preferred:
            return len(_EXPLICIT_TIME_PRIORITY) + 10 - idx
        if preferred in lowered:
            return len(_EXPLICIT_TIME_PRIORITY) - idx
    if lowered.startswith("_"):
        return -10
    return 0


def _choose_time_column(
    *,
    columns: list[str],
    rows: list[dict[str, Any]],
    intent: dict[str, Any],
) -> tuple[str | None, str]:
    if not columns:
        return None, "no_columns"

    requested_time_validation_reason = ""
    requested_time = str(intent.get("time_column", "")).strip()
    if requested_time and requested_time in columns and requested_time.lower() not in _METADATA_TIME_EXACT:
        is_valid, reason = time_column_validator(
            selected_time_column=requested_time,
            available_columns=columns,
        )
        if is_valid:
            return requested_time, "intent_requested_time_column"
        requested_time_validation_reason = reason

    # Priority 1: explicit names (ds/date/datetime/timestamp), excluding metadata columns.
    explicit_candidates = [
        column for column in columns
        if _explicit_time_priority(column) > 0 and not is_technical_column_name(column)
    ]
    if explicit_candidates:
        explicit_candidates.sort(key=_explicit_time_priority, reverse=True)
        chosen = explicit_candidates[0]
        return chosen, "explicit_time_name_priority"

    # Priority 2: parseable temporal columns with highest parse ratio.
    scored: list[tuple[float, int, str]] = []
    for idx, column in enumerate(columns):
        lowered = str(column).strip().lower()
        if lowered in _METADATA_TIME_EXACT or is_technical_column_name(lowered):
            continue
        populated = 0
        parsed = 0
        for row in rows:
            value = row.get(column)
            if value in (None, ""):
                continue
            populated += 1
            if _parse_datetime(value) is not None:
                parsed += 1
        if populated == 0:
            continue
        ratio = parsed / populated
        if ratio >= 0.8:
            scored.append((ratio, -idx, column))
    if scored:
        scored.sort(reverse=True)
        return scored[0][2], "temporal_parse_ratio"

    # Priority 3: intent dimensions fallback (historical trend pattern).
    dimensions = intent.get("dimensions", [])
    if isinstance(dimensions, list):
        for dim in dimensions:
            dim_name = str(dim).strip()
            if (
                dim_name in columns
                and dim_name.lower() not in _METADATA_TIME_EXACT
                and not is_technical_column_name(dim_name)
            ):
                return dim_name, "intent_dimensions_fallback"
    return None, requested_time_validation_reason or "time_column_not_found"


def _choose_value_column(
    *,
    columns: list[str],
    rows: list[dict[str, Any]],
    time_column: str,
    intent: dict[str, Any],
) -> str | None:
    metric_hints: list[str] = []
    metric_value = str(intent.get("metric", "")).strip()
    if metric_value:
        metric_hints.append(metric_value)
    target_column = str(intent.get("target_column", "")).strip()
    if target_column:
        metric_hints.append(target_column)
    metrics = intent.get("metrics", [])
    if isinstance(metrics, list):
        for metric in metrics:
            if isinstance(metric, str):
                metric_hints.append(metric.strip())
            elif isinstance(metric, dict):
                metric_hints.append(str(metric.get("column", "")).strip())
    for hint in metric_hints:
        if hint and hint in columns and hint != time_column:
            if is_technical_column_name(hint):
                continue
            numeric_ratio = 0
            populated = 0
            for row in rows:
                value = row.get(hint)
                if value in (None, ""):
                    continue
                populated += 1
                if _is_numeric(value):
                    numeric_ratio += 1
            if populated > 0 and (numeric_ratio / populated) >= 0.8:
                return hint

    candidates: list[tuple[float, int, str]] = []
    for idx, column in enumerate(columns):
        if column == time_column:
            continue
        if is_technical_column_name(column):
            continue
        populated = 0
        numeric = 0
        for row in rows:
            value = row.get(column)
            if value in (None, ""):
                continue
            populated += 1
            if _is_numeric(value):
                numeric += 1
        if populated == 0:
            continue
        ratio = numeric / populated
        if ratio < 0.8:
            continue
        name_boost = 1 if any(token in column.lower() for token in ("value", "sales", "revenue", "amount", "total", "y")) else 0
        candidates.append((ratio + name_boost, -idx, column))

    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][2]


def _sorted_series(rows: list[dict[str, Any]], time_column: str, value_column: str) -> list[tuple[datetime, float]]:
    cleaned: list[tuple[datetime, float]] = []
    for row in rows:
        dt = _parse_datetime(row.get(time_column))
        value = _to_float(row.get(value_column))
        if dt is None or value is None or not math.isfinite(value):
            continue
        cleaned.append((dt, value))

    if not cleaned:
        raise ForecastingError(
            "empty_time_series",
            "No valid points were found after cleaning time series rows.",
            details={"time_column": time_column, "value_column": value_column},
        )

    deduped: dict[datetime, float] = {}
    for dt, value in cleaned:
        deduped[dt] = value
    ordered = sorted(deduped.items(), key=lambda item: item[0])
    return ordered


def _infer_frequency(sorted_points: list[tuple[datetime, float]]) -> timedelta:
    if len(sorted_points) < 2:
        return timedelta(days=1)
    deltas: list[float] = []
    for index in range(1, len(sorted_points)):
        delta_sec = (sorted_points[index][0] - sorted_points[index - 1][0]).total_seconds()
        if delta_sec > 0:
            deltas.append(delta_sec)
    if not deltas:
        return timedelta(days=1)
    return timedelta(seconds=statistics.median(deltas))


def _validate_spacing_consistency(sorted_points: list[tuple[datetime, float]]) -> tuple[bool, str]:
    if len(sorted_points) < 3:
        return True, "insufficient_points_for_spacing_validation"
    deltas = [
        (sorted_points[index][0] - sorted_points[index - 1][0]).total_seconds()
        for index in range(1, len(sorted_points))
        if (sorted_points[index][0] - sorted_points[index - 1][0]).total_seconds() > 0
    ]
    if len(deltas) < 2:
        return True, "insufficient_positive_deltas"
    median_delta = statistics.median(deltas)
    tolerance = max(1.0, median_delta * 0.2)
    consistent_count = sum(1 for delta in deltas if abs(delta - median_delta) <= tolerance)
    ratio = consistent_count / len(deltas)
    if ratio < 0.8:
        return False, f"inconsistent_spacing_ratio={ratio:.2f}"
    return True, "consistent_spacing"


def _frequency_to_granularity(frequency: timedelta) -> str:
    seconds = max(1, int(frequency.total_seconds()))
    if seconds <= 3600:
        return "hour"
    if seconds <= 86400:
        return "day"
    if seconds <= 86400 * 8:
        return "week"
    if seconds <= 86400 * 35:
        return "month"
    return "year"


def _format_ds(dt: datetime) -> str:
    if dt.hour == 0 and dt.minute == 0 and dt.second == 0 and dt.microsecond == 0:
        return dt.strftime("%Y-%m-%d")
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _escape_sql_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _build_inline_clickhouse_sql(rows: list[dict[str, Any]]) -> str:
    if not rows:
        raise ForecastingError(
            "empty_visualization_dataset",
            "Cannot build visualization SQL for an empty merged dataset.",
        )
    parts: list[str] = []
    for row in rows:
        ds = _escape_sql_string(str(row["ds"]))
        series_type = _escape_sql_string(str(row["series_type"]))
        value = float(row["value"])
        parts.append(
            "SELECT parseDateTimeBestEffort('{ds}') AS ds, toFloat64({value}) AS value, '{series_type}' AS series_type".format(
                ds=ds,
                value=value,
                series_type=series_type,
            )
        )
    union_sql = "\nUNION ALL\n".join(parts)
    return (
        "SELECT ds, value, series_type\n"
        "FROM (\n"
        f"{union_sql}\n"
        ")\n"
        "ORDER BY ds ASC, series_type ASC"
    )


def _series_row(dt: datetime, value: float, series_type: str) -> dict[str, Any]:
    config = FORECAST_SERIES_CONFIG.get(series_type, FORECAST_SERIES_CONFIG["actual"])
    return {
        "ds": _format_ds(dt),
        "value": float(value),
        "series_type": config["series_type"],
        "series_label": config["series_label"],
        "preferred_color_role": config["preferred_color_role"],
    }


def _chart_series_config(*, include_forecast: bool) -> list[dict[str, Any]]:
    keys = ["actual", "forecast"] if include_forecast else ["actual"]
    return [dict(FORECAST_SERIES_CONFIG[key]) for key in keys]


def _sort_series_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    series_order = {"actual": 0, "forecast": 1}

    def sort_key(row: dict[str, Any]) -> tuple[datetime, int]:
        parsed = _parse_datetime(row.get("ds"))
        if parsed is None:
            parsed = datetime.max
        row_series = str(row.get("series_type", "")).strip().lower()
        return parsed, series_order.get(row_series, 9)

    return sorted([row for row in rows if isinstance(row, dict)], key=sort_key)


def _validate_forecast_points(
    *,
    ordered: list[tuple[datetime, float]],
    forecast_points: list[tuple[datetime, float]],
    resolved_horizon: int,
    granularity: str,
) -> str:
    if len(forecast_points) != resolved_horizon:
        return f"forecast_horizon_mismatch:expected={resolved_horizon},actual={len(forecast_points)}"
    if not ordered or not forecast_points:
        return "forecast_points_missing"

    expected_start = ordered[-1][0] + timedelta(days=1)
    if granularity == "day" and forecast_points[0][0].date() != expected_start.date():
        return (
            "forecast_start_mismatch:"
            f"expected={expected_start.date().isoformat()},actual={forecast_points[0][0].date().isoformat()}"
        )

    if granularity == "day":
        for idx in range(1, len(forecast_points)):
            delta = forecast_points[idx][0] - forecast_points[idx - 1][0]
            if delta != timedelta(days=1):
                return (
                    "forecast_daily_spacing_invalid:"
                    f"index={idx},delta_seconds={int(delta.total_seconds())}"
                )
    return ""


def _build_historical_only_dataset(
    *,
    ordered: list[tuple[datetime, float]],
    time_column: str,
    value_column: str,
    reason: str,
    selected_time_column_reason: str,
    granularity: str,
    validation_message: str | None = None,
) -> dict[str, Any]:
    rows = [_series_row(dt, float(value), "actual") for dt, value in ordered]
    return {
        "columns": ["ds", "value", "series_type", "series_label", "preferred_color_role"],
        "rows": rows,
        "sql": _build_inline_clickhouse_sql(rows),
        "meta": {
            "time_column": time_column,
            "value_column": value_column,
            "actual_points": len(ordered),
            "forecast_points": 0,
            "forecast_start_date": "",
            "forecast_boundary_index": len(ordered),
            "horizon": 0,
            "frequency_seconds": int(_infer_frequency(ordered).total_seconds()) if ordered else 0,
            "granularity": granularity,
            "forecast_available": False,
            "visualization_mode": "historical_only",
            "forecast_unavailable_label": "Forecast unavailable",
            "selected_time_column_reason": selected_time_column_reason,
            "time_column_used": time_column,
            "reason_for_selection": selected_time_column_reason,
            "forecasting_model_status": {
                "provider": "none",
                "used_fallback": True,
                "fallback_reason": reason,
            },
            "fallback_reason": reason,
            "validation_message": validation_message or "",
            "quantiles": {},
            "chart_series_config": _chart_series_config(include_forecast=False),
        },
    }


def _fill_missing_values(values: list[float | None]) -> list[float]:
    if not values:
        return []
    filled = list(values)
    last_seen: float | None = None
    for idx, value in enumerate(filled):
        if value is None:
            continue
        last_seen = float(value)
        for backfill_idx in range(idx - 1, -1, -1):
            if filled[backfill_idx] is not None:
                break
            filled[backfill_idx] = last_seen
    if last_seen is None:
        return []
    for idx, value in enumerate(filled):
        if value is None:
            filled[idx] = last_seen
        else:
            last_seen = float(value)
            filled[idx] = last_seen
    return [float(value) for value in filled if value is not None]


def build_forecast_dataset(
    *,
    columns: list[str],
    rows: list[dict[str, Any]],
    intent: dict[str, Any] | None = None,
    horizon: int | None = None,
) -> dict[str, Any]:
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise ForecastingError(
            "invalid_query_result",
            "Query result must include 'columns' list and 'rows' list.",
        )

    intent_payload = intent if isinstance(intent, dict) else {}
    time_column, selected_time_column_reason = _choose_time_column(columns=columns, rows=rows, intent=intent_payload)
    if not time_column:
        raise ForecastingError(
            "time_column_not_found",
            "No valid business time column was detected in the SQL result.",
            details={"columns": columns, "selected_time_column_reason": selected_time_column_reason},
        )

    value_column = _choose_value_column(columns=columns, rows=rows, time_column=time_column, intent=intent_payload)
    if not value_column:
        raise ForecastingError(
            "value_column_not_found",
            "No single numeric value column was detected for forecasting.",
            details={"columns": columns, "time_column": time_column},
        )

    ordered = _sorted_series(rows, time_column, value_column)
    frequency = _infer_frequency(ordered)
    granularity = str(intent_payload.get("granularity", "")).strip().lower() or _frequency_to_granularity(frequency)
    if granularity not in {"hour", "day", "week", "month", "year"}:
        granularity = _frequency_to_granularity(frequency)

    min_points = max(5, _int_env("TIMESFM_MIN_POINTS", 14))
    spacing_ok, spacing_reason = _validate_spacing_consistency(ordered)
    forecast_input_valid, validation_message = forecasting_validator(
        actual_points=len(ordered),
        minimum_points=min_points,
        spacing_ok=spacing_ok,
        spacing_reason=spacing_reason,
    )
    if not forecast_input_valid:
        return _build_historical_only_dataset(
            ordered=ordered,
            time_column=time_column,
            value_column=value_column,
            reason=validation_message,
            selected_time_column_reason=selected_time_column_reason,
            granularity=granularity,
            validation_message=validation_message,
        )

    resolved_horizon = int(
        horizon
        or intent_payload.get("forecast_horizon")
        or _int_env("TIMESFM_DEFAULT_HORIZON", 12)
    )
    if resolved_horizon <= 0:
        return _build_historical_only_dataset(
            ordered=ordered,
            time_column=time_column,
            value_column=value_column,
            reason=f"invalid_horizon:{resolved_horizon}",
            selected_time_column_reason=selected_time_column_reason,
            granularity=granularity,
        )

    # Canonical forecasting series values aligned with chronological ds.
    values = _fill_missing_values([float(value) if math.isfinite(float(value)) else None for _, value in ordered])
    if not values or any(not math.isfinite(value) for value in values):
        return _build_historical_only_dataset(
            ordered=ordered,
            time_column=time_column,
            value_column=value_column,
            reason="invalid_cleaned_values",
            selected_time_column_reason=selected_time_column_reason,
            granularity=granularity,
        )

    forecast_output = forecast(values, horizon=resolved_horizon)
    forecast_values = forecast_output.get("point_forecast", [])
    if not isinstance(forecast_values, list) or not forecast_values:
        return _build_historical_only_dataset(
            ordered=ordered,
            time_column=time_column,
            value_column=value_column,
            reason="empty_forecast_output",
            selected_time_column_reason=selected_time_column_reason,
            granularity=granularity,
        )

    last_dt = ordered[-1][0]
    forecast_points: list[tuple[datetime, float]] = []
    for idx, value in enumerate(forecast_values, start=1):
        forecast_points.append((last_dt + (frequency * idx), float(value)))

    validation_error = _validate_forecast_points(
        ordered=ordered,
        forecast_points=forecast_points,
        resolved_horizon=resolved_horizon,
        granularity=granularity,
    )
    if validation_error:
        return _build_historical_only_dataset(
            ordered=ordered,
            time_column=time_column,
            value_column=value_column,
            reason=validation_error,
            selected_time_column_reason=selected_time_column_reason,
            granularity=granularity,
            validation_message=validation_error,
        )

    merged_rows_unsorted: list[dict[str, Any]] = [
        _series_row(dt, float(value), "actual")
        for dt, value in ordered
    ] + [
        _series_row(dt, float(value), "forecast")
        for dt, value in forecast_points
    ]
    merged_rows = _sort_series_rows(merged_rows_unsorted)

    model_status = forecast_output.get("model_status", {}) if isinstance(forecast_output.get("model_status"), dict) else {}
    fallback_reason = str(model_status.get("fallback_reason", "")).strip()
    forecast_start_date = _format_ds(forecast_points[0][0]) if forecast_points else ""
    return {
        "columns": ["ds", "value", "series_type", "series_label", "preferred_color_role"],
        "rows": merged_rows,
        "sql": _build_inline_clickhouse_sql(merged_rows),
        "meta": {
            "time_column": time_column,
            "value_column": value_column,
            "actual_points": len(ordered),
            "forecast_points": len(forecast_points),
            "forecast_start_date": forecast_start_date,
            "forecast_boundary_index": len(ordered),
            "horizon": resolved_horizon,
            "frequency_seconds": int(frequency.total_seconds()),
            "granularity": granularity,
            "forecast_available": True,
            "visualization_mode": "historical_plus_forecast",
            "forecast_unavailable_label": "",
            "selected_time_column_reason": selected_time_column_reason,
            "time_column_used": time_column,
            "reason_for_selection": selected_time_column_reason,
            "forecasting_model_status": model_status,
            "fallback_reason": fallback_reason,
            "validation_message": "",
            "quantiles": forecast_output.get("quantiles", {}),
            "chart_series_config": _chart_series_config(include_forecast=True),
        },
    }
