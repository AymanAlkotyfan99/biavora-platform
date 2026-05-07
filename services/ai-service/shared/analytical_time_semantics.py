"""Deterministic analytical time semantics (phrase detection + intent repair)."""

from __future__ import annotations

import re
from typing import Any

from shared.schema_utils import is_numeric_type

_TIME_PHRASE_REGEXES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("day", re.compile(r"\bover\s+time\b|\btrend(s)?\b|\bby\s+date\b|\bby\s+day\b|\bdaily\b|\bper\s+day\b", re.I)),
    ("week", re.compile(r"\bweekly\b|\bper\s+week\b|\bby\s+week\b", re.I)),
    ("month", re.compile(r"\bmonthly\b|\bper\s+month\b|\bby\s+month\b", re.I)),
    ("quarter", re.compile(r"\bquarterly\b|\bper\s+quarter\b|\bby\s+quarter\b", re.I)),
    ("year", re.compile(r"\byearly\b|\bannually\b|\bannual\b|\bper\s+year\b|\bby\s+year\b", re.I)),
)


def question_requests_analytical_time(question: str) -> bool:
    q = str(question or "").strip().lower()
    if not q:
        return False
    for _grain, pattern in _TIME_PHRASE_REGEXES:
        if pattern.search(q):
            return True
    return False


def infer_time_grain_from_question(question: str) -> str:
    q = str(question or "").strip().lower()
    if not q:
        return ""
    for grain, pattern in _TIME_PHRASE_REGEXES:
        if pattern.search(q):
            return grain
    return ""


def _schema_has_ds(schema: dict[str, list[dict[str, Any]]] | None) -> bool:
    if not isinstance(schema, dict):
        return False
    for cols in schema.values():
        if not isinstance(cols, list):
            continue
        for c in cols:
            if isinstance(c, dict) and str(c.get("name", "")).strip().lower() == "ds":
                return True
    return False


def _numeric_columns(schema: dict[str, list[dict[str, Any]]] | None) -> set[str]:
    names: set[str] = set()
    if not isinstance(schema, dict):
        return names
    for cols in schema.values():
        if not isinstance(cols, list):
            continue
        for c in cols:
            if not isinstance(c, dict):
                continue
            n = str(c.get("name", "")).strip()
            if n and is_numeric_type(str(c.get("type", ""))):
                names.add(n)
    return names


def apply_deterministic_analytical_time_repair(
    *,
    intent: dict[str, Any],
    question: str,
    schema: dict[str, list[dict[str, Any]]] | None,
    preprocess_hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Force time-series IR when the question contains analytical time phrases."""

    out = dict(intent) if isinstance(intent, dict) else {}
    q = str(question or "").strip()
    if not question_requests_analytical_time(q):
        return out

    if str(out.get("intent_type", "analytical")).strip().lower() not in {"", "analytical"}:
        return out

    grain = infer_time_grain_from_question(q) or "day"
    has_ds = _schema_has_ds(schema)
    time_col = "ds" if has_ds else str(out.get("time_column") or "").strip()
    if not time_col:
        return out

    metrics = out.get("metrics") if isinstance(out.get("metrics"), list) else []
    metric_cols: list[str] = []
    for m in metrics:
        if isinstance(m, dict):
            c = str(m.get("column") or "").strip()
        else:
            c = str(m).strip()
        if c and c != "*":
            metric_cols.append(c)

    numeric = _numeric_columns(schema)
    if not metric_cols and isinstance((preprocess_hints or {}).get("selected_columns"), list):
        for raw in preprocess_hints["selected_columns"]:  # type: ignore[index]
            c = str(raw).strip()
            if c.lower() == "ds" or not c:
                continue
            if not numeric or c in numeric:
                metric_cols.append(c)

    if not metric_cols:
        return out

    out["group_by_time"] = True
    out["time_grouping_detected"] = True
    out["is_time_series"] = True
    out["time_dimension"] = "ds" if has_ds else time_col
    out["time_column"] = time_col
    out["time_granularity"] = grain
    out["time_dimension_alias"] = "date"

    dims = out.get("dimensions") if isinstance(out.get("dimensions"), list) else []
    dims = [str(d).strip() for d in dims if str(d).strip()]
    if time_col and time_col not in dims:
        dims.insert(0, time_col)
    out["dimensions"] = dims

    ops = out.get("operations") if isinstance(out.get("operations"), list) else []
    op_set = {str(o).strip().lower() for o in ops if str(o).strip()}
    for token in ("time_grouping", "grouping", "aggregation", "multi_metric"):
        if token not in op_set:
            ops.append(token)
            op_set.add(token)
    out["operations"] = ops

    out["order_by"] = [{"column": "date", "direction": "ASC"}]
    specs = out.get("metric_specs") if isinstance(out.get("metric_specs"), list) else []
    specs_by_col: dict[str, dict[str, Any]] = {}
    for s in specs:
        if isinstance(s, dict) and str(s.get("column", "")).strip():
            specs_by_col[str(s["column"]).strip()] = dict(s)

    new_specs: list[dict[str, Any]] = []
    for col in metric_cols:
        spec = dict(specs_by_col.get(col, {"column": col}))
        spec["column"] = col
        agg = str(spec.get("aggregation") or "").strip().upper()
        if col in numeric and agg not in {"COUNT", "AVG", "MIN", "MAX", "MEDIAN"}:
            spec["aggregation"] = "SUM"
            spec["alias"] = str(spec.get("alias") or "").strip() or col
        new_specs.append(spec)
    if new_specs:
        out["metric_specs"] = new_specs
        out["metrics"] = [str(s["column"]) for s in new_specs]

    if len(metric_cols) > 1:
        out["selected_chart_type"] = out["chart_type"] = "line_multi"
    else:
        out["selected_chart_type"] = out["chart_type"] = "line"
    out["final_chart_type"] = out["selected_chart_type"]
    out["chart"] = {
        **(out["chart"] if isinstance(out.get("chart"), dict) else {}),
        "type": out["chart_type"],
        "group_by": "date",
    }
    out["x_axis"] = "date"
    out["y_axis"] = [str(s.get("alias") or s.get("column")) for s in new_specs] if new_specs else list(metric_cols)
    return out
