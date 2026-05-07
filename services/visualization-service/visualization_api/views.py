"""
visualization-service views (post-CRIT-03 surgery).

Per the audit, visualization-service must NOT re-infer chart shape: it
consumes the ChartContract emitted by ai-service as-is and either renders
through Metabase (200 OK) or rejects (400 ``chart_contract_incompatible``).
voice-service handles orchestration; Metabase outages yield a **degraded**
HTTP 200 that preserves ``chart_contract`` / ``final_chart_type`` (no silent
table downgrade for locked contracts).
"""

from __future__ import annotations

import logging
import math
from typing import Any

from django.utils import timezone
from pydantic import ValidationError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from bi_platform_shared.contracts.chart import ChartContract, ChartTypeEnum
from visualization_api.application.chart_contract import (
    build_metabase_settings,
    check_structural_compatibility,
    coerce_upstream_chart_contract_dict,
)
from visualization_api.services import get_metabase_service

logger = logging.getLogger(__name__)


def _available_column_names(columns: list[Any], rows: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for column in columns or []:
        if isinstance(column, dict):
            name = str(column.get("name") or "").strip()
        else:
            name = str(column or "").strip()
        if name and name not in names:
            names.append(name)
    if not names and isinstance(rows, list) and rows and isinstance(rows[0], dict):
        for key in rows[0].keys():
            name = str(key or "").strip()
            if name and name not in names:
                names.append(name)
    return names


def _repair_chart_contract_once(contract: dict[str, Any], columns: list[Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    repaired = dict(contract)
    chart_type = str(repaired.get("chart_type") or repaired.get("type") or "").strip().lower()
    available = _available_column_names(columns, rows)
    metrics = repaired.get("y_axis") if isinstance(repaired.get("y_axis"), list) else []
    metrics = [str(m).strip() for m in metrics if str(m or "").strip()]
    if not metrics and isinstance(repaired.get("metrics"), list):
        metrics = [str(m).strip() for m in repaired.get("metrics", []) if str(m or "").strip()]
    x_axis = str(repaired.get("x_axis") or "").strip()
    dims = repaired.get("dimensions") if isinstance(repaired.get("dimensions"), list) else []
    dims = [str(d).strip() for d in dims if str(d or "").strip()]

    if chart_type == "histogram":
        if not x_axis:
            x_axis = metrics[0] if metrics else (available[0] if available else "")
        repaired["x_axis"] = x_axis
        if x_axis:
            repaired["dimensions"] = [x_axis]
    elif chart_type == "scatter":
        if len(metrics) < 2 and len(available) >= 2:
            metrics = [available[0], available[1]]
        if not x_axis and metrics:
            x_axis = metrics[0]
        repaired["x_axis"] = x_axis
        repaired["y_axis"] = [metrics[1]] if len(metrics) > 1 else ([metrics[0]] if metrics else [])
        repaired["metrics"] = list(repaired["y_axis"])
    elif chart_type == "pie":
        label = str(repaired.get("label_column") or "").strip() or x_axis or (dims[0] if dims else "")
        value = str(repaired.get("value_column") or "").strip() or (metrics[0] if metrics else "")
        if not label and available:
            label = available[0]
        if not value and len(available) > 1:
            value = available[1]
        repaired["label_column"] = label or None
        repaired["value_column"] = value or None
        repaired["x_axis"] = label or repaired.get("x_axis")
        repaired["y_axis"] = [value] if value else []
        repaired["metrics"] = [value] if value else []
        repaired["dimensions"] = [label] if label else []
    return repaired


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _build_histogram_sql_binning(
    *,
    sql: str,
    metric_column: str,
    rows: list[dict[str, Any]],
    desired_bins: int = 12,
) -> tuple[str, dict[str, Any]]:
    metric_values = [_to_float(row.get(metric_column)) for row in rows if isinstance(row, dict)]
    clean_values = [value for value in metric_values if value is not None]
    if not clean_values:
        return sql, {}

    min_val = min(clean_values)
    max_val = max(clean_values)
    value_range = max_val - min_val
    row_count = len(clean_values)
    bins_count = min(max(5, desired_bins), max(5, row_count))
    if value_range <= 0:
        bin_size = 1.0
    else:
        raw = value_range / float(bins_count)
        bin_size = max(1e-9, math.ceil(raw * 1000000.0) / 1000000.0)

    binned_sql = (
        "WITH source AS (\n"
        f"{sql}\n"
        ")\n"
        "SELECT\n"
        f"    floor(({metric_column}) / {bin_size}) * {bin_size} AS bucket,\n"
        "    count(*) AS frequency\n"
        "FROM source\n"
        f"WHERE {metric_column} IS NOT NULL\n"
        "GROUP BY bucket\n"
        "ORDER BY bucket ASC"
    )
    diagnostics = {
        "histogram_strategy": "sql_binning",
        "metric_column": metric_column,
        "bucket_column": "bucket",
        "frequency_column": "frequency",
        "bin_size": bin_size,
        "bins_count": bins_count,
    }
    return binned_sql, diagnostics


class VisualizationHealthView(APIView):
    permission_classes = []

    def get(self, request):
        metabase = get_metabase_service()
        healthy = metabase.authenticate()
        return Response(
            {
                "success": healthy,
                "service": "visualization-service",
                "error": metabase.last_error,
            },
            status=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        )


class CreateQuestionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        trace_timestamp = timezone.now().isoformat()
        name = request.data.get("name", "")
        sql = request.data.get("sql", "")
        rows = request.data.get("rows", []) or []
        columns = request.data.get("columns", []) or []
        raw_in = request.data.get("chart_contract")

        if not name or not sql:
            return Response(
                {"success": False, "error": "name and sql are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            if not isinstance(raw_in, dict) or not raw_in:
                raise ValueError("missing_chart_contract_from_ai")
            raw_contract = coerce_upstream_chart_contract_dict(raw_in)
        except ValueError as exc:
            logger.error("Chart contract missing - cannot render", extra={"reason": str(exc)})
            return Response(
                {
                    "success": False,
                    "error": "chart_contract_required",
                    "detail": str(exc),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            contract = ChartContract.model_validate(raw_contract)
        except ValidationError as exc:
            logger.warning("invalid_chart_contract", extra={"errors": exc.errors()})
            return Response(
                {
                    "error": "chart_contract_incompatible",
                    "detail": "chart_contract_validation_failed",
                    "validation_errors": exc.errors(),
                    "chart_contract": raw_contract,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        logger.info("Visualization using upstream chart type: %s", contract.chart_type.value)

        compatible, reason = check_structural_compatibility(contract, rows, columns)
        if not compatible:
            return Response(
                {
                    "error": "chart_contract_incompatible",
                    "detail": reason,
                    "chart_contract": contract.model_dump(),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        metabase = get_metabase_service()
        if not metabase.authenticate():
            # Preserve chart contract — orchestration treats this as degraded render, not chart-type failure.
            return Response(
                {
                    "success": True,
                    "status": "success",
                    "render_status": "degraded",
                    "contract_preserved": True,
                    "metabase_status": "unavailable",
                    "question_id": None,
                    "metabase_question_id": None,
                    "embed_url": None,
                    "chart_type": contract.chart_type.value,
                    "final_chart_type": contract.chart_type.value,
                    "chart_contract": contract.model_dump(),
                    "user_message": "Chart configuration is ready but Metabase is unavailable",
                    "trace": [
                        {
                            "stage_name": "visualization_render",
                            "status": "degraded",
                            "service": "visualization-service",
                            "timestamp": trace_timestamp,
                            "detail": metabase.last_error or "metabase_authentication_failed",
                        }
                    ],
                },
                status=status.HTTP_200_OK,
            )

        renderer_sql = sql
        try:
            outbound_settings = build_metabase_settings(contract, rows, columns, extra_settings={"chart_contract": raw_contract})
        except ValueError as exc:
            logger.warning(
                "invalid_chart_contract_fail_fast",
                extra={"error": str(exc), "chart_contract": raw_contract},
            )
            return Response(
                {
                    "error": "chart_contract_incompatible",
                    "detail": str(exc),
                    "chart_contract": contract.model_dump(),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if contract.chart_type.value == ChartTypeEnum.HISTOGRAM.value:
            metric_column = str(contract.x_axis or "").strip()
            available_columns = set(_available_column_names(columns, rows))
            already_binned = {"bucket", "frequency"}.issubset(available_columns)
            if metric_column and metric_column in available_columns and not already_binned:
                rewritten_sql, histogram_diag = _build_histogram_sql_binning(
                    sql=sql,
                    metric_column=metric_column,
                    rows=rows if isinstance(rows, list) else [],
                )
                renderer_sql = rewritten_sql
                if histogram_diag:
                    outbound_settings["histogram_strategy"] = histogram_diag["histogram_strategy"]
                    outbound_settings["semantic_chart_type"] = ChartTypeEnum.HISTOGRAM.value
                    outbound_settings["renderer_chart_type"] = "bar"
                    outbound_settings["graph.dimensions"] = ["bucket"]
                    outbound_settings["graph.metrics"] = ["frequency"]
                    outbound_settings["x_axis"] = "bucket"
                    outbound_settings["y_axis"] = ["frequency"]
                    outbound_settings["bucket_column"] = "bucket"
                    outbound_settings["frequency_column"] = "frequency"
                    outbound_settings["bin_size"] = histogram_diag["bin_size"]
                    outbound_settings["bins_count"] = histogram_diag["bins_count"]
                    logger.info(
                        "histogram_renderer_strategy semantic=%s renderer=%s strategy=%s metric=%s bucket=%s freq=%s bin_size=%s bins=%s",
                        "histogram",
                        "bar",
                        histogram_diag["histogram_strategy"],
                        histogram_diag["metric_column"],
                        histogram_diag["bucket_column"],
                        histogram_diag["frequency_column"],
                        histogram_diag["bin_size"],
                        histogram_diag["bins_count"],
                    )
            elif already_binned:
                logger.info(
                    "histogram_renderer_strategy skipped_sql_rewrite reason=already_binned metric=%s",
                    metric_column or "",
                )
        question_id = metabase.create_question(
            name=name,
            sql=renderer_sql,
            visualization_settings=outbound_settings,
        )
        if not question_id:
            err = str(metabase.last_error or "question_creation_failed")
            retried = False
            if err.startswith(("missing_", "invalid_chart_contract", "unsupported_metabase_display", "unsupported_")):
                retried = True
                repaired_raw = _repair_chart_contract_once(contract.model_dump(), columns, rows)
                try:
                    repaired_contract = ChartContract.model_validate(coerce_upstream_chart_contract_dict(repaired_raw))
                    repaired_settings = build_metabase_settings(
                        repaired_contract,
                        rows,
                        columns,
                        extra_settings={"chart_contract": repaired_raw},
                    )
                    question_id = metabase.create_question(
                        name=name,
                        sql=sql,
                        visualization_settings=repaired_settings,
                    )
                    if question_id:
                        contract = repaired_contract
                        outbound_settings = repaired_settings
                except Exception as retry_exc:  # noqa: BLE001
                    logger.warning("chart_contract_retry_failed", extra={"error": str(retry_exc)})
                err = str(metabase.last_error or err)
            if err.startswith(
                ("missing_", "unsupported_metabase_display", "unsupported_", "metabase_prepare")
            ):
                return Response(
                    {
                        "success": False,
                        "error": "chart_contract_incompatible",
                        "detail": err,
                        "retry_attempted": retried,
                        "chart_contract": contract.model_dump(),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if isinstance(rows, list) and len(rows) > 0:
                logger.error(
                    "metabase_render_failure_due_to_invalid_contract",
                    extra={
                        "row_count": len(rows),
                        "chart_contract": raw_contract,
                        "visualization_settings": outbound_settings,
                        "metabase_error": err,
                    },
                )
                return Response(
                    {
                        "success": False,
                        "error": "metabase_render_failure_invalid_contract",
                        "detail": "Metabase render failure due to invalid contract",
                        "metabase_error": err,
                        "chart_contract": contract.model_dump(),
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            return Response(
                {
                    "success": False,
                    "error": "metabase_render_failed",
                    "detail": err,
                    "chart_contract": contract.model_dump(),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        metabase.enable_question_embedding(question_id)
        return Response(
            {
                "success": True,
                "status": "success",
                "render_status": "success",
                "contract_preserved": True,
                "question_id": question_id,
                "metabase_question_id": question_id,
                "chart_type": contract.chart_type.value,
                "final_chart_type": contract.chart_type.value,
                "chart_contract": contract.model_dump(),
                "trace": [
                    {
                        "stage_name": "visualization_render",
                        "status": "success",
                        "service": "visualization-service",
                        "timestamp": trace_timestamp,
                    }
                ],
            },
            status=status.HTTP_200_OK,
        )


class CreateEmptyStateCardView(APIView):
    """GAP-04: render a Metabase 'No results' card when a query returned 0 rows."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        sql = request.data.get("sql", "")
        message = request.data.get("message") or "Your query ran but returned no rows."
        name = request.data.get("name") or "Empty result"
        if not sql:
            return Response(
                {"success": False, "error": "sql is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        metabase = get_metabase_service()
        if not metabase.authenticate():
            return Response(
                {"success": False, "error": metabase.last_error or "metabase_authentication_failed"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        outbound_settings: dict[str, Any] = {
            "display": "table",
            "chart_type": ChartTypeEnum.TABLE.value,
            "empty_state_message": message,
            "explicit_chart_lock": True,
            "chart_locked": True,
        }
        question_id = metabase.create_question(
            name=name,
            sql=sql,
            visualization_settings=outbound_settings,
        )
        if not question_id:
            return Response(
                {"success": False, "error": metabase.last_error or "question_creation_failed"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        metabase.enable_question_embedding(question_id)
        return Response(
            {
                "success": True,
                "question_id": question_id,
                "metabase_question_id": question_id,
                "embed_url": metabase.get_question_embed_url(question_id),
                "empty_state_message": message,
            },
            status=status.HTTP_200_OK,
        )


class CreateDashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        name = request.data.get("name", "")
        description = request.data.get("description", "")
        if not name:
            return Response(
                {"success": False, "error": "name is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        metabase = get_metabase_service()
        if not metabase.authenticate():
            return Response(
                {"success": False, "error": metabase.last_error or "metabase_authentication_failed"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        dashboard_id = metabase.create_dashboard(name=name, description=description)
        if not dashboard_id:
            return Response(
                {"success": False, "error": metabase.last_error or "dashboard_creation_failed"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        metabase.enable_dashboard_embedding(dashboard_id)
        return Response({"success": True, "dashboard_id": dashboard_id}, status=status.HTTP_200_OK)


class AddQuestionToDashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        question_id = request.data.get("question_id")
        dashboard_id = request.data.get("dashboard_id")
        if question_id is None or dashboard_id is None:
            return Response(
                {"success": False, "error": "question_id and dashboard_id are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        metabase = get_metabase_service()
        if not metabase.authenticate():
            return Response(
                {"success": False, "error": metabase.last_error or "metabase_authentication_failed"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        added = metabase.add_question_to_dashboard(question_id, dashboard_id)
        if not added:
            return Response(
                {"success": False, "error": metabase.last_error or "add_to_dashboard_failed"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({"success": True}, status=status.HTTP_200_OK)


class QuestionEmbedUrlView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, question_id):
        metabase = get_metabase_service()
        url = metabase.get_question_embed_url(question_id)
        if not url:
            return Response(
                {"success": False, "error": metabase.last_error or "question_embed_url_failed"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({"success": True, "embed_url": url}, status=status.HTTP_200_OK)


class DashboardEmbedUrlView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, dashboard_id):
        metabase = get_metabase_service()
        url = metabase.get_dashboard_embed_url(dashboard_id)
        if not url:
            return Response(
                {"success": False, "error": metabase.last_error or "dashboard_embed_url_failed"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({"success": True, "embed_url": url}, status=status.HTTP_200_OK)
