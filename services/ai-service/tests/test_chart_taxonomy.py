import os
import sys


sys.path.insert(0, os.path.abspath("services/ai-service"))

from shared.chart_types import (  # noqa: E402
    ChartType,
    normalize_chart_type,
    to_metabase_display,
    validate_chart_type,
)


def test_validate_chart_type_accepts_canonical():
    assert validate_chart_type("bar_grouped") == ChartType.BAR_GROUPED.value
    assert validate_chart_type("line_multi") == ChartType.LINE_MULTI.value


def test_validate_chart_type_maps_legacy_values():
    assert validate_chart_type("grouped_bar") == ChartType.BAR_GROUPED.value
    assert validate_chart_type("kpi") == ChartType.CARD.value
    assert normalize_chart_type("stacked_bar") == ChartType.BAR_STACKED.value


def test_validate_chart_type_raises_on_unknown_without_default():
    try:
        validate_chart_type("unknown_type")
        assert False, "validate_chart_type should raise ValueError for unknown types"
    except ValueError:
        assert True


def test_metabase_display_mapping_supports_new_types():
    assert to_metabase_display("pie") == "pie"
    assert to_metabase_display("area") == "area"
    assert to_metabase_display("combo_line_bar") == "combo"
