"""report-service voice_reports.constants.

Per CRIT-03 the chart taxonomy lives in ``bi_platform_shared.contracts.chart``.
The ``ChartType`` and helper names are re-exported here as thin aliases so
the existing migrations and models continue to work unchanged.
"""

from bi_platform_shared.contracts.chart import (
    ChartContract,
    ChartTypeEnum as ChartType,
    normalize_chart_type,
    to_metabase_display,
)

VALID_CHART_TYPES = {member.value for member in ChartType}

__all__ = [
    "ChartContract",
    "ChartType",
    "VALID_CHART_TYPES",
    "normalize_chart_type",
    "to_metabase_display",
]
