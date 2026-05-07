"""Tests for deterministic chart selector."""

import pytest
from shared.deterministic_chart_selector import (
    select_chart_deterministic,
    apply_chart_selection,
    enforce_chart_lock,
    ChartSelection,
)


class TestDeterministicChartSelector:
    """Test deterministic chart selection."""
    
    def test_time_series_multi_metric_line_multi(self):
        """Test time series + multi-metric → line_multi (LOCKED)."""
        result = select_chart_deterministic(
            is_time_series=True,
            number_of_metrics=2,
            has_categorical_dimension=False,
            has_grouping=True,
        )
        
        assert result.chart_type == "line_multi"
        assert result.chart_lock is True
        assert result.confidence == 1.0
    
    def test_time_series_single_metric_line(self):
        """Test time series + single metric → line (LOCKED)."""
        result = select_chart_deterministic(
            is_time_series=True,
            number_of_metrics=1,
            has_categorical_dimension=False,
            has_grouping=True,
        )
        
        assert result.chart_type == "line"
        assert result.chart_lock is True
        assert result.confidence == 1.0
    
    def test_categorical_multi_metric_bar_grouped(self):
        """Test categorical + multi-metric → bar_grouped."""
        result = select_chart_deterministic(
            is_time_series=False,
            number_of_metrics=2,
            has_categorical_dimension=True,
            has_grouping=True,
        )
        
        assert result.chart_type == "bar_grouped"
        assert result.chart_lock is False
    
    def test_categorical_single_metric_bar(self):
        """Test categorical + single metric → bar."""
        result = select_chart_deterministic(
            is_time_series=False,
            number_of_metrics=1,
            has_categorical_dimension=True,
            has_grouping=True,
        )
        
        assert result.chart_type == "bar"
        assert result.chart_lock is False
    
    def test_single_value_card(self):
        """Test single value → card."""
        result = select_chart_deterministic(
            is_time_series=False,
            number_of_metrics=1,
            has_categorical_dimension=False,
            has_grouping=False,
        )
        
        assert result.chart_type == "card"
        assert result.chart_lock is False
    
    def test_fallback_table(self):
        """Test fallback → table."""
        result = select_chart_deterministic(
            is_time_series=False,
            number_of_metrics=0,
            has_categorical_dimension=False,
            has_grouping=False,
        )
        
        assert result.chart_type == "table"
        assert result.chart_lock is False
    
    def test_apply_chart_selection(self):
        """Test applying chart selection to intent."""
        intent = {
            "is_time_series": True,
            "metrics": [
                {"column": "sales", "aggregation": "SUM"},
                {"column": "customers", "aggregation": "SUM"}
            ],
            "dimensions": ["ds"],
        }
        
        enriched = apply_chart_selection(intent)
        
        assert enriched["chart_type"] == "line_multi"
        assert enriched["chart_lock"] is True
        assert "chart_selection_reason" in enriched

    def test_percentage_overrides_time_series(self):
        intent = {
            "is_time_series": True,
            "time_grouping_detected": True,
            "metrics": [{"column": "total_sales", "aggregation": "SUM"}],
            "dimensions": ["ds"],
        }
        enriched = apply_chart_selection(intent, user_query="percentage share of total sales by day")
        assert enriched["chart_type"] == "pie"
        assert enriched["is_time_series"] is False

    def test_distribution_overrides_time_series(self):
        intent = {
            "is_time_series": True,
            "metrics": [{"column": "total_sales", "aggregation": "SUM"}],
            "dimensions": ["ds"],
        }
        enriched = apply_chart_selection(intent, user_query="distribution of total sales by month")
        assert enriched["chart_type"] == "histogram"
        assert enriched["is_time_series"] is False

    def test_relationship_priority_uses_scatter(self):
        intent = {
            "is_time_series": True,
            "metrics": [
                {"column": "total_sales", "aggregation": "SUM"},
                {"column": "orders", "aggregation": "SUM"},
            ],
            "dimensions": ["ds"],
        }
        enriched = apply_chart_selection(intent, user_query="relationship between sales and orders by day")
        assert enriched["chart_type"] == "scatter"

    def test_explicit_pie_chart_lock_prevents_line_override(self):
        intent = {
            "is_time_series": True,
            "time_grouping_detected": True,
            "metrics": [{"column": "total_sales", "aggregation": "SUM"}],
            "dimensions": ["month"],
        }
        enriched = apply_chart_selection(
            intent,
            user_query="Show the percentage share of total_sales by month as a pie chart",
        )
        assert enriched["chart_type"] == "pie"
        assert enriched["chart_lock"] is True
        assert enriched["chart_reason_code"].startswith("explicit_user_chart")

    def test_percentage_trend_over_time_prefers_line(self):
        intent = {
            "is_time_series": True,
            "time_grouping_detected": True,
            "metrics": [{"column": "total_sales", "aggregation": "SUM"}],
            "dimensions": ["ds"],
        }
        enriched = apply_chart_selection(intent, user_query="show percentage trend over time")
        assert enriched["chart_type"] == "line"
    
    def test_enforce_chart_lock_locked(self):
        """Test chart lock enforcement when locked."""
        final_chart = enforce_chart_lock(
            intent_chart_type="line_multi",
            chart_lock=True,
            downstream_chart_type="table"
        )
        
        assert final_chart == "line_multi"  # Intent wins
    
    def test_enforce_chart_lock_unlocked(self):
        """Test chart lock enforcement when unlocked."""
        final_chart = enforce_chart_lock(
            intent_chart_type="bar",
            chart_lock=False,
            downstream_chart_type="table"
        )
        
        assert final_chart == "table"  # Downstream wins
