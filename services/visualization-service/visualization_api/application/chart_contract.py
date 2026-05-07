"""
visualization-service Metabase payload builder (post-CRIT-03 surgery).

The previous module owned a 300-line shape-inference + chart-recovery engine
that duplicated logic found in ai-service. Per CRIT-03 the only valid input
to visualization-service is a fully-formed ``ChartContract`` produced by
ai-service. This module is now a small, deterministic translator from a
canonical contract into Metabase ``visualization_settings``. It MUST NOT
re-infer chart shape; if the contract does not bind to the result columns,
``views.CreateQuestionView`` returns HTTP 400 ``chart_contract_incompatible``.
"""

from __future__ import annotations

from typing import Any, Dict, List

from bi_platform_shared.contracts.chart import (
    ChartContract,
    ChartTypeEnum,
    normalize_chart_type,
    to_metabase_display,
)

_UPSTREAM_CHART_IDENTITY_KEYS = (
    "chart_type",
    "type",
    "final_chart_type",
    "selected_chart_type",
)


def coerce_upstream_chart_contract_dict(raw: Any) -> dict[str, Any]:
    """Normalize upstream payloads into keys :class:`ChartContract` accepts.

    Raises ``ValueError`` when no chart identity is present — the renderer
    must not guess ``chart_type`` (including defaulting to ``table``).
    """

    if not isinstance(raw, dict):
        raise ValueError("chart_contract_must_be_object")
    out: dict[str, Any] = dict(raw)
    identity: str | None = None
    for key in _UPSTREAM_CHART_IDENTITY_KEYS:
        token = str(out.get(key) or "").strip()
        if token:
            identity = token.lower()
            break
    if not identity:
        raise ValueError("missing_chart_contract_type")
    canonical = normalize_chart_type(identity)
    if canonical == ChartTypeEnum.TABLE and identity not in {
        "table",
        "card",
        "kpi",
        "scalar",
        "number",
    }:
        raise ValueError(f"unsupported_or_unknown_chart_type:{identity}")
    out["chart_type"] = canonical.value

    if not str(out.get("x_axis") or "").strip() and str(out.get("time_column") or "").strip():
        out["x_axis"] = str(out.get("time_column")).strip()
    if not out.get("y_axis") and isinstance(out.get("metrics"), list):
        out["y_axis"] = [str(m).strip() for m in out["metrics"] if str(m or "").strip()]
    elif not out.get("y_axis") and isinstance(out.get("metrics"), str) and out["metrics"].strip():
        out["y_axis"] = [out["metrics"].strip()]

    if "locked" not in out:
        if out.get("chart_lock") is not None:
            out["locked"] = bool(out.get("chart_lock"))
        elif out.get("explicit_chart_lock") is not None:
            out["locked"] = bool(out.get("explicit_chart_lock"))
    return out


def validate_chart_contract(
    *,
    rows: List[dict[str, Any]],
    columns: List[Any],
    chart_contract: dict[str, Any],
    requested_chart_type: str,
) -> dict[str, Any]:
    """Structural validation only — never downgrades chart type to ``table``."""

    coerced = coerce_upstream_chart_contract_dict(chart_contract)
    contract = ChartContract.model_validate(coerced)
    ok, reason = check_structural_compatibility(contract, rows, columns)
    ct = contract.chart_type.value
    if not ok:
        return {
            "requested_chart_type": str(requested_chart_type or ct),
            "final_chart_type": ct,
            "fallback_used": False,
            "fallback_reason": reason or "chart_contract_incompatible",
        }
    return {
        "requested_chart_type": ct,
        "final_chart_type": ct,
        "fallback_used": False,
        "fallback_reason": "",
    }


def _column_names(rows: List[dict[str, Any]], columns: List[Any]) -> List[str]:
    explicit: List[str] = []
    for column in columns or []:
        if isinstance(column, dict):
            name = str(column.get("name") or "").strip()
        else:
            name = str(column or "").strip()
        if name:
            explicit.append(name)
    if explicit:
        return explicit
    if rows and isinstance(rows[0], dict):
        return [str(key) for key in rows[0].keys()]
    return []


def check_structural_compatibility(
    contract: ChartContract,
    rows: List[dict[str, Any]],
    columns: List[Any],
) -> tuple[bool, str | None]:
    """Return (compatible, reason) without re-inferring chart shape.

    The structural check is intentionally minimal: every column the contract
    references (``x_axis``, ``y_axis``, ``label_column`` …) must appear in
    the result column set. We do not second-guess data types or aggregation
    correctness — that is ai-service's job.
    """

    available = set(_column_names(rows, columns))
    required = contract.required_columns()
    if not required:
        if contract.chart_type in {ChartTypeEnum.TABLE, ChartTypeEnum.CARD}:
            return True, None
        return False, "contract_missing_required_bindings"
    if not available:
        # Query has not been executed yet (empty preview): do not block Metabase creation.
        return True, None
    missing = [col for col in required if col not in available]
    if missing and contract.chart_type == ChartTypeEnum.HISTOGRAM:
        # Histogram is rendered through SQL binning in views.CreateQuestionView.
        # ``bucket`` / ``frequency`` are synthetic columns produced by rewritten
        # SQL, so they are allowed to be absent in the pre-rewrite result shape.
        synthetic_histogram_cols = {"bucket", "frequency"}
        if all(col in synthetic_histogram_cols for col in missing):
            return True, None
    if missing:
        return False, f"missing_columns:{','.join(missing)}"
    return True, None


def build_metabase_settings(
    contract: ChartContract,
    rows: List[dict[str, Any]],
    columns: List[Any],
    *,
    extra_settings: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Translate a canonical chart contract into Metabase visualization_settings.

    The output stays small and deterministic. No fallbacks are applied: when
    the contract is structurally invalid for the data, the caller has already
    returned 400.
    """

    base: Dict[str, Any] = dict(extra_settings or {})
    chart_type = contract.chart_type
    base.update(
        {
            "display": to_metabase_display(chart_type),
            "chart_type": chart_type.value,
            "selected_chart_type": chart_type.value,
            "explicit_chart_lock": True,
            "chart_locked": True,
            "chart_source": contract.chart_source,
        }
    )
    # Strict: the upstream contract MUST bind dimensions/metrics explicitly.
    # No inference, no fallback.
    if contract.x_axis:
        base["graph.dimensions"] = [contract.x_axis]
    if contract.y_axis:
        base["graph.metrics"] = list(contract.y_axis)
    if contract.label_column:
        base["label_field"] = contract.label_column
    if contract.value_column:
        base["value_field"] = contract.value_column
    if contract.bin_column:
        base["bin_field"] = contract.bin_column
    if contract.bin_count:
        base["bin_count"] = int(contract.bin_count)
    if contract.series_dimension:
        base["graph.series_dimension"] = contract.series_dimension

    graph_dims = base.get("graph.dimensions")
    graph_mets = base.get("graph.metrics")
    if not isinstance(graph_dims, list) or not [d for d in graph_dims if str(d or "").strip()]:
        raise ValueError("invalid_chart_contract:missing_x_axis_dimension")
    if chart_type not in {ChartTypeEnum.CARD, ChartTypeEnum.TABLE}:
        if not isinstance(graph_mets, list) or not [m for m in graph_mets if str(m or "").strip()]:
            raise ValueError("invalid_chart_contract:missing_metrics")

    if chart_type == ChartTypeEnum.LINE_MULTI:
        metrics = [str(m).strip() for m in (base.get("graph.metrics") or []) if str(m or "").strip()]
        base["series_settings"] = {m: {"display": "line"} for m in metrics}
    elif chart_type == ChartTypeEnum.PIE:
        # Metabase pie renderer needs explicit field bindings; otherwise it may
        # render the "choose columns" prompt even when graph.* exists.
        pie_dim = str(contract.label_column or contract.x_axis or "").strip()
        pie_metric = str(contract.value_column or (contract.y_axis[0] if contract.y_axis else "")).strip()
        if pie_dim:
            base["pie.dimension"] = pie_dim
        if pie_metric:
            base["pie.metric"] = pie_metric

    # Metabase "graph" contract mirror (used by downstream adapters / audits).
    base["graph"] = {
        "type": "line" if chart_type in {ChartTypeEnum.LINE, ChartTypeEnum.LINE_MULTI, ChartTypeEnum.AREA} else base.get("display"),
        "dimensions": [str(d).strip() for d in (base.get("graph.dimensions") or []) if str(d or "").strip()],
        "metrics": [str(m).strip() for m in (base.get("graph.metrics") or []) if str(m or "").strip()],
    }
    return base


__all__ = [
    "ChartContract",
    "ChartTypeEnum",
    "build_metabase_settings",
    "check_structural_compatibility",
    "coerce_upstream_chart_contract_dict",
    "validate_chart_contract",
]
