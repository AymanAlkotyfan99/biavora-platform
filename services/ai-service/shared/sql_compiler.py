import os
import re
from typing import Any

from shared.schema_utils import is_numeric_type, normalize_table_name, unqualify_table_name

VALID_AGGREGATIONS = {"SUM", "AVG", "COUNT", "MIN", "MAX"}
VALID_DIRECTIONS = {"ASC", "DESC"}
VALID_OPERATORS = {"=", "!=", ">", "<", ">=", "<=", "IN", "LIKE", "BETWEEN"}
TIME_GRANULARITY_EXPRESSIONS = {
    "day": "toDate({column})",
    "week": "toStartOfWeek(toDate({column}))",
    "month": "toStartOfMonth(toDate({column}))",
    "quarter": "toStartOfQuarter(toDate({column}))",
    "year": "toStartOfYear(toDate({column}))",
}
BUSINESS_METRIC_HINT_TOKENS = (
    "sales",
    "total_sales",
    "revenue",
    "orders",
    "order_count",
    "customers",
    "customer_count",
    "quantity",
    "amount",
)


# Phase 6 / CRIT-05: default ClickHouse settings injected at the head of every
# generated query. They are encoded as a structured comment so the executor
# can parse them deterministically and apply them via ``SETTINGS``.
DEFAULT_CH_SETTINGS = {
    "max_execution_time": 60,
    "max_result_rows": 100_000,
    "readonly": 2,
}


def _format_ch_settings(settings: dict[str, Any]) -> str:
    """Produce the canonical ``/* ch_settings: ... */`` header.

    Phase 6 / CRIT-05: every compiled query carries this header so
    downstream services (sql_review, query-service executor) can apply the
    same execution limits without re-implementing them.
    """

    parts: list[str] = []
    for key, value in sorted((settings or {}).items()):
        key_str = str(key).strip()
        if not key_str:
            continue
        if isinstance(value, bool):
            value_str = "1" if value else "0"
        elif isinstance(value, (int, float)):
            value_str = str(value)
        else:
            value_str = str(value).replace("*/", "")
        parts.append(f"{key_str}={value_str}")
    return "/* ch_settings: " + ", ".join(parts) + " */" if parts else ""


def _resolve_workspace_db(
    *,
    intent: dict[str, Any],
    workspace_clickhouse_db: str | None,
) -> str:
    """Resolve the per-tenant ClickHouse database used to qualify the table.

    Phase 6 / CRIT-05: the legacy ``CLICKHOUSE_DATABASE=etl`` default is
    forbidden. The compiler accepts ``workspace_clickhouse_db`` either as an
    explicit kwarg or through ``intent['workspace_clickhouse_db']``. As a
    very last resort it reads ``CLICKHOUSE_DATABASE`` (for legacy unit tests
    that still rely on the env var). It never silently falls back to the
    string ``"etl"``.
    """

    candidate = ""
    raw = (
        workspace_clickhouse_db
        or intent.get("workspace_clickhouse_db")
        or intent.get("clickhouse_db")
    )
    if isinstance(raw, str):
        candidate = raw.strip()
    if not candidate:
        # Audit Phase 6 / CRIT-05: NO hardcoded ``etl`` fallback. We only
        # honour the env var when an operator has *explicitly* set it (we
        # do not provide ``"etl"`` as the default any more).
        env_value = str(os.getenv("CLICKHOUSE_DATABASE", "")).strip()
        if env_value:
            candidate = env_value
    if not candidate:
        raise ValueError(
            "compile_sql requires a workspace ClickHouse database (workspace_clickhouse_db). "
            "No tenant database was supplied and CLICKHOUSE_DATABASE is not set."
        )
    return candidate


def compile_sql(
    intent: dict[str, Any],
    schema: dict[str, list[dict[str, Any]]],
    *,
    workspace_clickhouse_db: str | None = None,
    ch_settings: dict[str, Any] | None = None,
) -> str:
    """Compile structured intent into a ClickHouse-flavoured SQL statement.

    Phase 6 / CRIT-05:
    - ``workspace_clickhouse_db`` (or ``intent['workspace_clickhouse_db']``)
      is **required** so the FROM clause is always per-tenant qualified
      (``<workspace_db>.<table>``). The legacy ``etl`` default has been
      removed.
    - The compiled SQL carries a canonical ``/* ch_settings: ... */`` header
      so downstream services can apply identical execution limits.
    - Histograms never produce a raw ``GROUP BY`` over the continuous
      column; we always materialise a bucket expression.
    """

    raw_table = intent.get("table")
    if not raw_table:
        raise ValueError("Intent is missing table name")
    default_db = _resolve_workspace_db(
        intent=intent,
        workspace_clickhouse_db=workspace_clickhouse_db,
    )

    from_table = _normalize_and_validate_table_name(raw_table, default_db)
    schema_table = _resolve_schema_table_name(raw_table, schema)
    if not schema_table:
        schema_table = _resolve_schema_table_name(unqualify_table_name(from_table), schema)
    if not schema_table:
        raise ValueError(f"Table '{raw_table}' does not exist in schema")

    columns = schema[schema_table]
    column_map = {col["name"]: col for col in columns}

    metrics = intent.get("metrics") or []
    if not metrics:
        raise ValueError("Intent must contain at least one metric")

    dimensions = intent.get("dimensions") or []
    filters = intent.get("filters") or []
    order_by = intent.get("order_by") or []
    limit = intent.get("limit")
    type_cast_map = _build_type_cast_map(intent.get("type_casting") or intent.get("type_casting_needed") or [])
    time_granularity = str(intent.get("time_granularity", "")).strip().lower()
    time_column = str(intent.get("time_column", "")).strip()
    time_grouping_detected = bool(intent.get("time_grouping_detected") or intent.get("group_by_time"))
    row_count_requested = bool(intent.get("row_count_requested"))
    time_dimension_alias = str(intent.get("time_dimension_alias", "")).strip() or (
        "date" if time_grouping_detected else "period"
    )
    time_dimension_expression = str(intent.get("time_dimension_expression", "")).strip()
    explicit_top_n_requested = bool(intent.get("explicit_top_n_requested"))
    metric_type = str(intent.get("metric_type", "")).strip().lower()
    is_percentage_intent = bool(intent.get("is_percentage")) or metric_type in {"percentage", "percent", "ratio"}
    # Phase 6 / CRIT-05: histogram dimensions must be bucketed, never raw.
    selected_chart_type = (
        str(intent.get("selected_chart_type", "")).strip().lower()
        or str(intent.get("chart_type", "")).strip().lower()
        or str((intent.get("chart") or {}).get("type", "")).strip().lower()
    )
    # Respect explicit upstream chart lock/type. Distribution-like operations
    # should not force histogram SQL when the selected chart is pie/line/etc.
    distribution_requested = bool(intent.get("is_distribution")) or (
        "distribution" in {str(op).strip().lower() for op in (intent.get("operations") or [])}
    )
    is_histogram_intent = (
        selected_chart_type == "histogram"
        or (
            distribution_requested
            and selected_chart_type in {"", "histogram"}
        )
    )
    histogram_bin_count_raw = intent.get("histogram_bin_count")
    try:
        histogram_bin_count = max(2, min(200, int(histogram_bin_count_raw)))
    except (TypeError, ValueError):
        histogram_bin_count = 20
    if (
        time_grouping_detected
        and time_granularity in TIME_GRANULARITY_EXPRESSIONS
        and time_column
    ):
        time_dimension_expression = _build_time_dimension_expression(
            granularity=time_granularity,
            column_name=time_column,
            column_map=column_map,
        )

    # Distribution intent must compile to histogram buckets directly in SQL.
    if is_histogram_intent:
        histogram_metric = ""
        for metric in metrics:
            if isinstance(metric, dict):
                candidate = str(metric.get("column") or "").strip()
            else:
                candidate = str(metric or "").strip()
            if candidate and candidate in column_map and is_numeric_type(column_map[candidate].get("type", "")):
                histogram_metric = candidate
                break
        if not histogram_metric:
            for candidate in dimensions:
                if candidate in column_map and is_numeric_type(column_map[candidate].get("type", "")):
                    histogram_metric = candidate
                    break
        if not histogram_metric:
            raise ValueError("Histogram intent requires a numeric metric column.")

        where_clause = _build_where_clause(filters, column_map, type_cast_map)
        where_sql = f"\n{where_clause}" if where_clause else ""
        settings_to_emit: dict[str, Any] = dict(DEFAULT_CH_SETTINGS)
        if isinstance(intent.get("ch_settings"), dict):
            settings_to_emit.update(intent["ch_settings"])
        if ch_settings:
            settings_to_emit.update(ch_settings)
        settings_comment = _format_ch_settings(settings_to_emit)

        stats_tail = (
            f"{where_sql}\n      AND {histogram_metric} IS NOT NULL"
            if where_clause
            else f"\n    WHERE {histogram_metric} IS NOT NULL\n"
        )
        histogram_sql = (
            "WITH stats AS (\n"
            f"    SELECT min({histogram_metric}) AS min_value,\n"
            f"           max({histogram_metric}) AS max_value,\n"
            "           count(*) AS row_count\n"
            f"    FROM {from_table}"
            f"{stats_tail}"
        )
        histogram_sql += (
            "), params AS (\n"
            "    SELECT\n"
            "        min_value,\n"
            "        max_value,\n"
            "        row_count,\n"
            "        least(30.0, greatest(5.0, sqrt(greatest(row_count, 1)))) AS bins,\n"
            "        greatest(1.0, (max_value - min_value) / least(30.0, greatest(5.0, sqrt(greatest(row_count, 1))))) AS bin_size\n"
            "    FROM stats\n"
            ")\n"
            "SELECT floor(t."
            + histogram_metric
            + " / p.bin_size) * p.bin_size AS bucket,\n"
            "       count(*) AS frequency\n"
            f"FROM {from_table} AS t\n"
            "CROSS JOIN params AS p"
        )
        if where_clause:
            histogram_sql += f"\n{where_clause} AND t.{histogram_metric} IS NOT NULL"
        else:
            histogram_sql += f"\nWHERE t.{histogram_metric} IS NOT NULL"
        histogram_sql += "\nGROUP BY bucket\nORDER BY bucket ASC;"
        histogram_sql = _normalize_clickhouse_date_casts(histogram_sql)
        _validate_sql_structure(histogram_sql)
        if settings_comment:
            histogram_sql = f"{settings_comment}\n{histogram_sql}"
        return histogram_sql

    select_parts: list[str] = []
    group_by_parts: list[str] = []
    metric_aliases: dict[str, str] = {}
    dimension_aliases: dict[str, str] = {}
    alias_by_column: dict[str, list[str]] = {}
    has_aggregated_metric = False

    for dim in dimensions:
        if dim not in column_map:
            raise ValueError(f"Dimension column '{dim}' does not exist in table '{schema_table}'")
        if (
            time_grouping_detected
            and time_dimension_expression
            and time_column
            and dim == time_column
        ):
            select_parts.append(f"{time_dimension_expression} AS {time_dimension_alias}")
            group_by_parts.append(time_dimension_alias)
            dimension_aliases[time_dimension_alias] = time_dimension_alias
            continue
        # Phase 6 / CRIT-05: histogram on a continuous numeric column must
        # bucket the column rather than ``GROUP BY`` the raw value, which
        # would explode cardinality and break downstream rendering.
        if is_histogram_intent and is_numeric_type(column_map[dim].get("type", "")):
            bin_alias = f"{dim}_bin"
            bin_expression = (
                f"(floor(({dim} - (SELECT min({dim}) FROM {from_table})) / "
                f"((SELECT (max({dim}) - min({dim})) FROM {from_table}) / {histogram_bin_count})) * "
                f"((SELECT (max({dim}) - min({dim})) FROM {from_table}) / {histogram_bin_count}) + "
                f"(SELECT min({dim}) FROM {from_table}))"
            )
            select_parts.append(f"{bin_expression} AS {bin_alias}")
            group_by_parts.append(bin_alias)
            dimension_aliases[bin_alias] = bin_alias
            continue
        select_parts.append(dim)
        group_by_parts.append(dim)
        dimension_aliases[dim] = dim

    for metric in metrics:
        if not isinstance(metric, dict):
            raise ValueError("Each metric in IR must be an object")

        column = metric.get("column")
        formula = metric.get("formula") if isinstance(metric.get("formula"), dict) else {}
        raw_aggregation = metric.get("aggregation")
        aggregation = (raw_aggregation or "").upper()
        if aggregation in {"", "NONE", "NULL"}:
            aggregation = ""
        needs_agg_default = bool(time_grouping_detected or dimensions) and not row_count_requested
        if (
            needs_agg_default
            and not aggregation
            and isinstance(column, str)
            and column not in ("*", "")
            and column in column_map
            and is_numeric_type(column_map[column].get("type", ""))
        ):
            aggregation = "SUM"
        if (
            aggregation == "COUNT"
            and not row_count_requested
            and isinstance(column, str)
            and column != "*"
            and _is_business_metric_column_name(column)
            and is_numeric_type(column_map.get(column, {}).get("type", ""))
        ):
            aggregation = "SUM"
        alias = metric.get("alias") or _default_metric_alias(aggregation, column)

        if formula:
            expression, formula_uses_aggregation = _compile_formula_expression(
                formula=formula,
                column_map=column_map,
                type_cast_map=type_cast_map,
            )
            has_aggregated_metric = has_aggregated_metric or formula_uses_aggregation
        else:
            if aggregation and aggregation not in VALID_AGGREGATIONS:
                raise ValueError(f"Unsupported aggregation '{aggregation}'")

            if column == "*":
                if aggregation not in {"COUNT", ""}:
                    raise ValueError("Only COUNT supports '*' metric column")
                expression = "COUNT(*)" if aggregation == "COUNT" else "*"
            else:
                if column not in column_map:
                    raise ValueError(f"Metric column '{column}' does not exist in table '{schema_table}'")
                cast_target = type_cast_map.get(column)
                metric_expr = _metric_expression(column=column, cast_target=cast_target)
                if aggregation and aggregation != "COUNT" and not (
                    cast_target or is_numeric_type(column_map[column].get("type", ""))
                ):
                    raise ValueError(
                        f"Aggregation '{aggregation}' requires numeric column, got '{column}' ({column_map[column].get('type')})"
                    )
                if aggregation:
                    base_expression = f"{aggregation}({metric_expr})"
                    if is_percentage_intent and aggregation in {"SUM", "COUNT", "AVG", "MIN", "MAX"}:
                        expression = f"({base_expression} / NULLIF(SUM({base_expression}) OVER (), 0))"
                    else:
                        expression = base_expression
                    has_aggregated_metric = True
                else:
                    expression = metric_expr

        if alias and alias != expression:
            select_parts.append(f"{expression} AS {alias}")
            if column:
                alias_by_column.setdefault(str(column), []).append(alias)
            metric_aliases[alias] = alias
        else:
            select_parts.append(expression)
            if column:
                alias_by_column.setdefault(str(column), []).append(str(column))
            if isinstance(column, str):
                metric_aliases[column] = column

    for column_name, aliases in alias_by_column.items():
        unique_aliases = [alias for alias in aliases if alias]
        if len(set(unique_aliases)) == 1:
            metric_aliases[column_name] = unique_aliases[0]

    if select_parts:
        deduped_select_parts: list[str] = []
        seen_select_parts: set[str] = set()
        for part in select_parts:
            if part in seen_select_parts:
                continue
            seen_select_parts.add(part)
            deduped_select_parts.append(part)
        select_parts = deduped_select_parts

    if not select_parts:
        raise ValueError("SQL generation failed: empty SELECT list")

    if has_aggregated_metric:
        for metric in metrics:
            if not isinstance(metric, dict):
                continue
            aggregation = (metric.get("aggregation") or "").upper()
            if aggregation in {"", "NONE", "NULL"}:
                column = metric.get("column")
                if column and column != "*" and column not in group_by_parts:
                    group_by_parts.append(column)

    ranking_payload = intent.get("ranking") if isinstance(intent.get("ranking"), dict) else {}
    ranking_requested = bool(str(ranking_payload.get("direction", "")).strip().upper() in VALID_DIRECTIONS)
    limit_present = isinstance(limit, int) and limit > 0
    explicit_intent = str(intent.get("intent", "")).strip().lower()
    operations = intent.get("operations") if isinstance(intent.get("operations"), list) else []
    kpi_allowed = bool(intent.get("kpi_allowed_without_dimension", False))
    if "overall" in explicit_intent:
        kpi_allowed = True

    if has_aggregated_metric and ranking_requested and limit_present and not group_by_parts and not kpi_allowed:
        inferable_dimension = _infer_groupable_dimension(columns)
        if inferable_dimension:
            raise ValueError(
                "Unsafe ranking SQL shape: aggregation with LIMIT requires GROUP BY when a dimension is inferable."
            )
    if has_aggregated_metric and limit_present and "ranking" in {str(op).lower() for op in operations} and not group_by_parts and not kpi_allowed:
        inferable_dimension = _infer_groupable_dimension(columns)
        if inferable_dimension:
            raise ValueError(
                "Unsafe ranking SQL shape: LIMIT + aggregation without GROUP BY is blocked."
            )
    if has_aggregated_metric and time_grouping_detected and time_dimension_alias not in group_by_parts:
        raise ValueError("Unsafe time-grouped SQL shape: aggregation over time requires GROUP BY transformed time dimension.")

    where_clause = _build_where_clause(filters, column_map, type_cast_map)
    if time_grouping_detected and time_column and _is_string_like_type(column_map.get(time_column, {}).get("type", "")):
        parsed_time_expr = _string_time_parse_expr(time_column)
        extra_predicates = [f"{parsed_time_expr} IS NOT NULL"]
        for metric in metrics:
            if not isinstance(metric, dict):
                continue
            metric_column = str(metric.get("column", "")).strip()
            if metric_column and metric_column != "*" and metric_column in column_map:
                extra_predicates.append(f"{metric_column} IS NOT NULL")
        deduped_predicates: list[str] = []
        seen_predicates: set[str] = set()
        for predicate in extra_predicates:
            if predicate in seen_predicates:
                continue
            seen_predicates.add(predicate)
            deduped_predicates.append(predicate)
        if deduped_predicates:
            if where_clause:
                where_clause = f"{where_clause} AND " + " AND ".join(deduped_predicates)
            else:
                where_clause = "WHERE " + " AND ".join(deduped_predicates)
    if has_aggregated_metric and time_grouping_detected and time_dimension_alias and not ranking_requested:
        order_by = [{"column": time_dimension_alias, "direction": "ASC"}]
    if time_grouping_detected and not explicit_top_n_requested and not ranking_requested:
        limit = None
    order_clause = _build_order_clause(order_by, column_map, metric_aliases, dimension_aliases)
    limit_clause = _build_limit_clause(limit)

    sql_parts = [
        _format_select_clause(select_parts),
        f"FROM {from_table}",
    ]
    if where_clause:
        sql_parts.append(where_clause)
    if has_aggregated_metric and group_by_parts:
        sql_parts.append(f"GROUP BY {', '.join(group_by_parts)}")
    if order_clause:
        sql_parts.append(order_clause)
    if limit_clause:
        sql_parts.append(limit_clause)

    final_sql = "\n".join(sql_parts) + ";"
    final_sql = _normalize_clickhouse_date_casts(final_sql)
    _validate_sql_structure(final_sql)

    # Phase 6 / CRIT-05: prepend a canonical ClickHouse settings comment so
    # downstream services (sql_review, query-service executor) can apply
    # identical execution limits without re-deriving them.
    settings_to_emit: dict[str, Any] = dict(DEFAULT_CH_SETTINGS)
    if isinstance(intent.get("ch_settings"), dict):
        settings_to_emit.update(intent["ch_settings"])
    if ch_settings:
        settings_to_emit.update(ch_settings)
    settings_comment = _format_ch_settings(settings_to_emit)
    if settings_comment:
        final_sql = f"{settings_comment}\n{final_sql}"
    return final_sql


def _resolve_schema_table_name(table_name: str, schema: dict[str, list[dict[str, Any]]]) -> str | None:
    if not table_name:
        return None
    if table_name in schema:
        return table_name

    table_unqualified = unqualify_table_name(table_name).lower()
    matches = [key for key in schema.keys() if unqualify_table_name(key).lower() == table_unqualified]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(
            f"Ambiguous table name '{table_name}'. Matches: {', '.join(matches)}"
        )
    return None


def _normalize_and_validate_table_name(table_name: str, default_db: str) -> str:
    normalized = normalize_table_name(table_name, default_db)
    segments = [seg for seg in normalized.split(".") if seg]

    # Defensive guard against malformed db.db.table patterns.
    if len(segments) >= 3 and segments[0].lower() == segments[1].lower():
        normalized = normalize_table_name(".".join(segments[1:]), default_db)
        segments = [seg for seg in normalized.split(".") if seg]

    if len(segments) != 2:
        raise ValueError(f"Invalid table reference '{table_name}' after normalization -> '{normalized}'")
    return normalized


def _default_metric_alias(aggregation: str, column: str) -> str:
    safe_column = (column or "metric").replace(".", "_")
    if safe_column == "*":
        safe_column = "rows"
    if not aggregation:
        return safe_column
    return f"{aggregation.lower()}_{safe_column}"


def _build_type_cast_map(type_casting: list[dict[str, Any]]) -> dict[str, str]:
    cast_map: dict[str, str] = {}
    for cast_item in type_casting:
        if not isinstance(cast_item, dict):
            continue
        column = str(cast_item.get("column", "")).strip()
        target = str(cast_item.get("required_cast", "")).strip().upper()
        if not column or not target:
            continue
        cast_map[column] = target
    return cast_map


def _metric_expression(*, column: str, cast_target: str | None) -> str:
    if cast_target:
        return f"CAST({column} AS {cast_target})"
    return column


def _resolve_formula_operand_expression(
    *,
    operand: dict[str, Any],
    column_map: dict[str, dict[str, Any]],
    type_cast_map: dict[str, str],
) -> tuple[str, bool]:
    column = str(operand.get("column", "")).strip()
    if not column:
        raise ValueError("Formula operand is missing column")
    if column not in column_map:
        raise ValueError(f"Formula column '{column}' does not exist in selected table")
    aggregation = str(operand.get("aggregation", "")).strip().upper()
    cast_target = type_cast_map.get(column)
    metric_expr = _metric_expression(column=column, cast_target=cast_target)
    if aggregation:
        if aggregation not in VALID_AGGREGATIONS:
            raise ValueError(f"Unsupported aggregation '{aggregation}' in formula operand")
        if aggregation != "COUNT" and not (cast_target or is_numeric_type(column_map[column].get("type", ""))):
            raise ValueError(
                f"Aggregation '{aggregation}' requires numeric column, got '{column}' ({column_map[column].get('type')})"
            )
        return f"{aggregation}({metric_expr})", True
    return metric_expr, False


def _compile_formula_expression(
    *,
    formula: dict[str, Any],
    column_map: dict[str, dict[str, Any]],
    type_cast_map: dict[str, str],
) -> tuple[str, bool]:
    formula_type = str(formula.get("type", "")).strip().lower()
    if formula_type != "ratio":
        raise ValueError(f"Unsupported metric formula type '{formula_type}'")
    numerator = formula.get("numerator") if isinstance(formula.get("numerator"), dict) else {}
    denominator = formula.get("denominator") if isinstance(formula.get("denominator"), dict) else {}
    numerator_expr, numerator_agg = _resolve_formula_operand_expression(
        operand=numerator,
        column_map=column_map,
        type_cast_map=type_cast_map,
    )
    denominator_expr, denominator_agg = _resolve_formula_operand_expression(
        operand=denominator,
        column_map=column_map,
        type_cast_map=type_cast_map,
    )
    safe_division = bool(formula.get("safe_division", True))
    denominator_sql = f"NULLIF({denominator_expr}, 0)" if safe_division else denominator_expr
    return f"({numerator_expr} / {denominator_sql})", numerator_agg or denominator_agg


def _format_filter_value(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        formatted = ", ".join(_format_filter_value(v) for v in value)
        return f"({formatted})"
    value_str = str(value).replace("'", "''")
    return f"'{value_str}'"


def _build_where_clause(
    filters: list[dict[str, Any]],
    column_map: dict[str, dict[str, Any]],
    type_cast_map: dict[str, str],
) -> str:
    clauses = []
    for filter_item in filters:
        if not isinstance(filter_item, dict):
            raise ValueError("Each filter in IR must be an object")
        column = filter_item.get("column")
        operator = (filter_item.get("operator") or "=").upper()
        value = filter_item.get("value")

        if not column:
            raise ValueError("Filter is missing required field 'column'")
        if column not in column_map:
            raise ValueError(f"Filter column '{column}' does not exist in selected table")
        if value is None:
            raise ValueError(f"Filter for column '{column}' is missing a value")
        if operator not in VALID_OPERATORS:
            raise ValueError(f"Unsupported filter operator '{operator}' for column '{column}'")

        filter_expr = _metric_expression(column=column, cast_target=type_cast_map.get(column))

        if operator == "IN":
            if not isinstance(value, list):
                value = [value]
            if not value:
                raise ValueError(f"Filter column '{column}' uses IN with an empty value list")
            value_sql = _format_filter_value(value)
            clauses.append(f"{filter_expr} IN {value_sql}")
        elif operator == "BETWEEN":
            if isinstance(value, (list, tuple)) and len(value) == 2:
                low_value, high_value = value[0], value[1]
            elif isinstance(value, dict):
                low_value = value.get("low")
                high_value = value.get("high")
            else:
                raise ValueError(
                    f"Filter column '{column}' uses BETWEEN but value must be [low, high] or {{low, high}}"
                )
            if low_value is None or high_value is None:
                raise ValueError(f"Filter column '{column}' uses BETWEEN but one boundary is missing")
            low_sql = _format_filter_value(low_value)
            high_sql = _format_filter_value(high_value)
            clauses.append(f"{filter_expr} BETWEEN {low_sql} AND {high_sql}")
        else:
            value_sql = _format_filter_value(value)
            clauses.append(f"{filter_expr} {operator} {value_sql}")

    if not clauses:
        return ""
    return "WHERE " + " AND ".join(clauses)


def _build_order_clause(
    order_by: list[dict[str, Any]],
    column_map: dict[str, dict[str, Any]],
    metric_aliases: dict[str, str],
    dimension_aliases: dict[str, str],
) -> str:
    clauses = []
    for order_item in order_by:
        if not isinstance(order_item, dict):
            raise ValueError("Each ORDER BY item in IR must be an object")
        raw_column = order_item.get("column")
        direction = (order_item.get("direction") or "ASC").upper()
        if direction not in VALID_DIRECTIONS:
            direction = "ASC"
        if not raw_column:
            raise ValueError("ORDER BY item is missing required field 'column'")

        column = metric_aliases.get(raw_column, raw_column)
        if (
            column not in metric_aliases.values()
            and column not in dimension_aliases.values()
            and column not in column_map
        ):
            raise ValueError(f"ORDER BY column '{raw_column}' is not present in metrics, aliases, or table columns")
        clauses.append(f"{column} {direction}")

    if not clauses:
        return ""
    return "ORDER BY " + ", ".join(clauses)


def _build_limit_clause(limit: Any) -> str:
    if isinstance(limit, int) and limit > 0:
        return f"LIMIT {limit}"
    return ""


def _format_select_clause(select_parts: list[str]) -> str:
    if not select_parts:
        raise ValueError("SQL generation failed: empty SELECT list")
    if len(select_parts) == 1:
        return f"SELECT {select_parts[0]}"
    head = select_parts[0]
    tail = ",\n       ".join(select_parts[1:])
    return f"SELECT {head},\n       {tail}"


def _validate_sql_structure(sql: str) -> None:
    sql_upper = sql.upper()
    if not re.search(r"\bSELECT\b", sql_upper):
        raise ValueError("SQL must contain SELECT")
    if not re.search(r"\bFROM\b", sql_upper):
        raise ValueError("SQL must contain FROM")
    if "GROUP BY ;" in sql_upper or "ORDER BY ;" in sql_upper:
        raise ValueError("SQL contains empty GROUP BY/ORDER BY clause")


def _is_string_like_type(column_type: str) -> bool:
    lowered = str(column_type or "").strip().lower()
    return any(token in lowered for token in ("string", "fixedstring", "varchar", "char"))


def _is_business_metric_column_name(column_name: str) -> bool:
    lowered = str(column_name or "").strip().lower()
    return any(token in lowered for token in BUSINESS_METRIC_HINT_TOKENS)


def _normalize_clickhouse_date_casts(sql: str) -> str:
    normalized = str(sql or "").strip()
    if not normalized:
        return normalized

    previous = ""
    while normalized != previous:
        previous = normalized
        normalized = re.sub(
            r"toDate\(\s*toDate\(\s*([^)]+?)\s*\)\s*\)",
            r"toDate(\1)",
            normalized,
            flags=re.IGNORECASE,
        )

    return normalized


def _build_time_dimension_expression(
    *,
    granularity: str,
    column_name: str,
    column_map: dict[str, dict[str, Any]],
) -> str:
    template = TIME_GRANULARITY_EXPRESSIONS.get(granularity, "")
    if not template or not column_name:
        return ""
    column_type = str(column_map.get(column_name, {}).get("type", "")).strip().lower()
    base_column = column_name
    if _is_string_like_type(column_type):
        parsed_expr = _string_time_parse_expr(column_name)
        if granularity == "day":
            return f"toDate({parsed_expr})"
        base_column = parsed_expr
    expression = template.format(column=base_column)
    return _normalize_clickhouse_date_casts(expression)


def _string_time_parse_expr(column_name: str) -> str:
    # Prefer US parsing for ambiguous M/D/YYYY sources, then fallback to generic parsing.
    return (
        f"coalesce("
        f"parseDateTimeBestEffortUSOrNull({column_name}), "
        f"parseDateTimeBestEffortOrNull({column_name})"
        f")"
    )


def _infer_groupable_dimension(columns: list[dict[str, Any]]) -> str | None:
    date_candidates: list[str] = []
    categorical_candidates: list[str] = []
    for col in columns:
        name = str(col.get("name", "")).strip()
        if not name:
            continue
        col_type = str(col.get("type", "")).strip()
        lowered = name.lower()
        if lowered in {"ds", "date", "timestamp", "created_at"} or "date" in lowered or "time" in lowered:
            date_candidates.append(name)
            continue
        if not is_numeric_type(col_type):
            categorical_candidates.append(name)

    if date_candidates:
        ranked = sorted(date_candidates, key=lambda c: (0 if c.lower() in {"ds", "date", "timestamp", "created_at"} else 1, c.lower()))
        return ranked[0]

    if categorical_candidates:
        preferred = ("region", "product", "category", "city")
        ranked = sorted(
            categorical_candidates,
            key=lambda c: (
                next(
                    (
                        idx
                        for idx, token in enumerate(preferred)
                        if token == c.lower() or c.lower().startswith(f"{token}_") or c.lower().endswith(f"_{token}") or token in c.lower()
                    ),
                    len(preferred),
                ),
                c.lower(),
            ),
        )
        return ranked[0]

    return None
