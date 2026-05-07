"""Time-aware SQL generation (PART 2 - ENFORCE TIME-AWARE SQL).

This module ensures that when is_time_series = True, the generated SQL
ALWAYS includes proper time grouping and ordering.

Phase: SQL Generation
Priority: CRITICAL - Ensures correct time-series queries
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def enforce_time_series_sql_structure(
    sql: str,
    time_column: str,
    time_granularity: str,
    metrics: list[dict[str, Any]],
) -> str:
    """Enforce time-series SQL structure.
    
    When is_time_series = True, SQL MUST have:
    1. Time column in SELECT with proper casting
    2. Metrics with aggregation
    3. GROUP BY time column
    4. ORDER BY time column ASC
    
    Args:
        sql: Generated SQL (may be incomplete)
        time_column: Time column name (e.g., "ds")
        time_granularity: Granularity (day, week, month)
        metrics: List of metric definitions
        
    Returns:
        SQL with enforced time-series structure
    """
    if not sql or not time_column:
        logger.error("enforce_time_series_sql_missing_inputs")
        return sql
    
    sql = sql.strip()
    sql_upper = sql.upper()
    
    # Check if SQL already has proper structure
    has_group_by = "GROUP BY" in sql_upper
    has_order_by = "ORDER BY" in sql_upper
    has_time_in_select = time_column.lower() in sql.lower()
    
    # If SQL is already well-formed, return it
    if has_group_by and has_order_by and has_time_in_select:
        logger.info("time_series_sql_already_valid")
        return sql
    
    # Extract table name
    from_match = re.search(r"\bFROM\s+([a-zA-Z0-9_.]+)", sql, re.IGNORECASE)
    if not from_match:
        logger.error("enforce_time_series_sql_no_table")
        return sql
    
    table_name = from_match.group(1)
    
    # Build time expression based on granularity
    time_expr = _build_time_expression(time_column, time_granularity)
    
    # Build metric expressions
    metric_exprs = []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        
        column = metric.get("column", "")
        aggregation = metric.get("aggregation", "SUM")
        alias = metric.get("alias", column)
        
        if column and column != "*":
            metric_exprs.append(f"{aggregation}({column}) AS {alias}")
    
    if not metric_exprs:
        # Fallback: count all
        metric_exprs.append("COUNT(*) AS count")
    
    # Build complete SQL
    select_clause = f"SELECT {time_expr} AS time, {', '.join(metric_exprs)}"
    from_clause = f"FROM {table_name}"
    group_by_clause = "GROUP BY time"
    order_by_clause = "ORDER BY time ASC"
    
    enforced_sql = f"{select_clause} {from_clause} {group_by_clause} {order_by_clause}"
    
    logger.info(
        "time_series_sql_enforced",
        extra={
            "original_sql": sql[:100],
            "enforced_sql": enforced_sql[:100],
            "time_column": time_column,
            "time_granularity": time_granularity,
        },
    )
    
    return enforced_sql


def _build_time_expression(time_column: str, time_granularity: str) -> str:
    """Build time expression for SELECT clause.
    
    Args:
        time_column: Time column name
        time_granularity: Granularity (day, week, month, quarter, year)
        
    Returns:
        ClickHouse time expression
    """
    if time_granularity == "day":
        return f"toDate({time_column})"
    elif time_granularity == "week":
        return f"toStartOfWeek(toDate({time_column}))"
    elif time_granularity == "month":
        return f"toStartOfMonth(toDate({time_column}))"
    elif time_granularity == "quarter":
        return f"toStartOfQuarter(toDate({time_column}))"
    elif time_granularity == "year":
        return f"toStartOfYear(toDate({time_column}))"
    else:
        # Default to day
        return f"toDate({time_column})"


def validate_time_series_sql(sql: str, time_column: str) -> tuple[bool, str]:
    """Validate that SQL has proper time-series structure.
    
    Args:
        sql: SQL to validate
        time_column: Expected time column
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not sql:
        return False, "SQL is empty"
    
    sql_upper = sql.upper()
    
    # Check for GROUP BY
    if "GROUP BY" not in sql_upper:
        return False, "Time-series SQL must include GROUP BY"
    
    # Check for ORDER BY
    if "ORDER BY" not in sql_upper:
        return False, "Time-series SQL must include ORDER BY"
    
    # Check for time column
    if time_column.lower() not in sql.lower():
        return False, f"Time-series SQL must include time column '{time_column}'"
    
    return True, "valid"


def enrich_intent_for_time_series_sql(intent: dict[str, Any]) -> dict[str, Any]:
    """Enrich intent with SQL generation hints for time-series.
    
    Args:
        intent: Intent JSON
        
    Returns:
        Enriched intent with SQL hints
    """
    if not isinstance(intent, dict):
        return intent
    
    if not intent.get("is_time_series"):
        return intent
    
    enriched = dict(intent)
    
    # Add SQL generation hints
    enriched["sql_hints"] = {
        "force_group_by": True,
        "force_order_by": True,
        "time_column_required": True,
        "aggregation_required": True,
    }
    
    # Ensure order_by includes time column
    time_column = enriched.get("time_column", "ds")
    order_by = enriched.get("order_by", [])
    if not isinstance(order_by, list):
        order_by = []
    
    # Check if time column already in order_by
    has_time_order = any(
        isinstance(item, dict) and item.get("column") == time_column
        for item in order_by
    )
    
    if not has_time_order:
        order_by.insert(0, {"column": time_column, "direction": "ASC"})
    
    enriched["order_by"] = order_by
    
    return enriched
