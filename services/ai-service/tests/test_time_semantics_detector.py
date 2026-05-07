"""Tests for time semantics detector."""

import pytest
from shared.time_semantics_detector import (
    detect_time_semantics,
    enrich_intent_with_time_semantics,
    TimeSemantics,
)


class TestTimeSemanticsDetector:
    """Test time semantics detection."""
    
    def test_detect_over_time(self):
        """Test detection of 'over time' phrase."""
        result = detect_time_semantics("Compare sales and customers over time")
        
        assert result.is_time_series is True
        assert result.time_grouping_detected is True
        assert result.time_column == "ds"
        assert result.time_granularity == "day"
        assert "over time" in result.detected_keywords
        assert result.confidence > 0
    
    def test_detect_trend(self):
        """Test detection of 'trend' keyword."""
        result = detect_time_semantics("Show sales trend")
        
        assert result.is_time_series is True
        assert "trend" in result.detected_keywords
    
    def test_detect_daily(self):
        """Test detection of 'daily' with correct granularity."""
        result = detect_time_semantics("Show daily sales")
        
        assert result.is_time_series is True
        assert result.time_granularity == "day"
        assert "daily" in result.detected_keywords
    
    def test_detect_weekly(self):
        """Test detection of 'weekly' with correct granularity."""
        result = detect_time_semantics("Show weekly revenue")
        
        assert result.is_time_series is True
        assert result.time_granularity == "week"
        assert "weekly" in result.detected_keywords
    
    def test_detect_monthly(self):
        """Test detection of 'monthly' with correct granularity."""
        result = detect_time_semantics("Show monthly growth")
        
        assert result.is_time_series is True
        assert result.time_granularity == "month"
    
    def test_detect_by_date(self):
        result = detect_time_semantics("Show revenue by date")
        assert result.is_time_series is True
        assert result.time_granularity == "day"
        assert "by date" in result.detected_keywords

    def test_no_time_keywords(self):
        """Test non-time-series query."""
        result = detect_time_semantics("Show total sales")
        
        assert result.is_time_series is False
        assert result.time_grouping_detected is False
        assert len(result.detected_keywords) == 0
    
    def test_time_column_from_schema(self):
        """Test time column detection from available columns."""
        result = detect_time_semantics(
            "Show sales over time",
            available_columns=["date", "sales", "customers"]
        )
        
        assert result.time_column == "date"
    
    def test_enrich_intent(self):
        """Test intent enrichment with time semantics."""
        time_semantics = TimeSemantics(
            is_time_series=True,
            time_grouping_detected=True,
            time_column="ds",
            time_granularity="day",
            detected_keywords=["over time"],
            confidence=0.3,
        )
        
        intent = {
            "table": "sales",
            "metrics": [{"column": "sales", "aggregation": "SUM"}],
            "dimensions": []
        }
        
        enriched = enrich_intent_with_time_semantics(intent, time_semantics)
        
        assert enriched["is_time_series"] is True
        assert enriched["time_column"] == "ds"
        assert enriched["time_granularity"] == "day"
        assert enriched.get("group_by_time") is True
        assert enriched.get("time_dimension") == "ds"
        assert "ds" in enriched["dimensions"]
    
    def test_multiple_time_keywords(self):
        """Test detection with multiple time keywords."""
        result = detect_time_semantics("Track daily sales trend over time")
        
        assert result.is_time_series is True
        assert len(result.detected_keywords) >= 2
        assert result.confidence > 0.3
