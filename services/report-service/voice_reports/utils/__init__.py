"""report-service voice_reports.utils — read-only helpers.

The chart-selection helpers (``extract_upstream_chart_type``,
``infer_chart_type``, ``infer_chart_with_reason``, ``profile_result_shape``)
were removed as part of CRIT-03: chart selection is owned exclusively by
ai-service via :mod:`bi_platform_shared.contracts.chart`.

Only the SQL normalization helpers used by the legacy migration / models
layer remain here.
"""

from .sql_normalization import normalize_sql_table_references, normalize_table_name

__all__ = [
    "normalize_sql_table_references",
    "normalize_table_name",
]
