"""SQL table-reference normalisation (Phase 7 / CRIT-05).

Phase 7 of the audit hardens this utility:

- When a table reference is bare (e.g. ``FROM orders``) we inject the
  workspace's ClickHouse database (``FROM <workspace_db>.orders``).
- When a table reference is already qualified with a *different* database we
  REJECT the SQL by raising :class:`CrossDatabaseViolationError`. This used
  to be silently passed through, allowing cross-tenant reads.

Both behaviours are exposed via the same public surface
(``normalize_sql_table_references`` / ``normalize_sql_table_references_detailed``)
so all existing callers (SQLGuard, executor) inherit the new safety.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

try:
    import sqlglot
    from sqlglot import exp
except Exception:  # pragma: no cover
    sqlglot = None
    exp = None


class CrossDatabaseViolationError(ValueError):
    """Raised when SQL references a database other than the workspace's.

    Carries the offending tables so the executor can build a precise
    ``cross_db_violation`` error message.
    """

    def __init__(self, offending_tables: List[str], expected_db: str) -> None:
        self.offending_tables = list(offending_tables)
        self.expected_db = expected_db
        super().__init__(
            f"cross_db_violation: SQL references databases other than '{expected_db}': "
            + ", ".join(self.offending_tables)
        )


def normalize_table_name(table_name: str, default_db: str) -> str:
    if not table_name or not table_name.strip():
        raise ValueError("table_name must be a non-empty string")
    if not default_db or not default_db.strip():
        raise ValueError("default_db must be a non-empty string")

    cleaned = table_name.strip().strip("`")
    parts = [part for part in cleaned.split(".") if part]
    if len(parts) == 1:
        return f"{default_db}.{parts[0]}"
    if len(parts) == 2:
        return f"{parts[0]}.{parts[1]}"
    return f"{parts[-2]}.{parts[-1]}"


def normalize_sql_table_references_detailed(sql: str, default_db: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "normalized_sql": sql,
        "normalization_applied": False,
        "warnings": [],
        "cross_db_violation": False,
        "offending_tables": [],
    }
    if not sql or not sql.strip():
        return result
    if not default_db or not default_db.strip():
        result["warnings"].append("missing_default_db")
        return result

    expected_db_lower = str(default_db).strip().lower()
    if sqlglot is None or exp is None:
        result["warnings"].append("sqlglot_unavailable")
        cte_names = {
            match.group(1).strip("`").lower()
            for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s+AS\s*\(", sql, flags=re.IGNORECASE)
        }
        offending_tables: List[str] = []

        def _replace(match: re.Match) -> str:
            clause = match.group(1)
            raw_table = match.group(2)
            table_name = raw_table.strip("`")
            if table_name.lower() in cte_names:
                return match.group(0)
            if "." in table_name:
                # Phase 7 / CRIT-05: reject any qualified table that points
                # at a database different from the workspace's.
                db_part = table_name.split(".", 1)[0].strip().strip("`").lower()
                if db_part and db_part != expected_db_lower:
                    offending_tables.append(table_name)
                return match.group(0)
            return f"{clause} {normalize_table_name(table_name, default_db)}"

        normalized = re.sub(
            r"\b(FROM|JOIN)\s+(`?[A-Za-z_][A-Za-z0-9_\.]*`?)",
            _replace,
            sql,
            flags=re.IGNORECASE,
        )
        if offending_tables:
            result["cross_db_violation"] = True
            result["offending_tables"] = offending_tables
            raise CrossDatabaseViolationError(offending_tables, default_db)
        result["normalized_sql"] = normalized
        result["normalization_applied"] = normalized != sql
        return result

    try:
        parsed = sqlglot.parse_one(sql, read="clickhouse")
    except Exception:
        result["warnings"].append("parse_failed")
        return result

    # Do not attempt risky rewrites when root is not SELECT-like.
    subqueryable_cls = getattr(exp, "Subqueryable", None) if exp is not None else None
    is_select_like_root = False
    if subqueryable_cls is not None:
        is_select_like_root = isinstance(parsed, subqueryable_cls)
    else:
        is_select_like_root = isinstance(parsed, exp.Select) or parsed.__class__.__name__ in {
            "Query",
            "Union",
            "Except",
            "Intersect",
        }
    if not is_select_like_root:
        result["warnings"].append("non_select_root_skipped")
        return result

    cte_names = {
        str(getattr(cte, "alias_or_name", "") or "").strip().strip("`").lower()
        for cte in parsed.find_all(exp.CTE)
        if str(getattr(cte, "alias_or_name", "") or "").strip()
    }

    offending_tables: List[str] = []
    changed = False
    for table in parsed.find_all(exp.Table):
        # Skip tables that are already fully qualified.
        db_name = str(table.db or "").strip().strip("`")
        table_name = str(table.name or "").strip().strip("`")
        if not table_name:
            continue
        if table_name.lower() in cte_names:
            continue
        if db_name:
            if db_name.lower() != expected_db_lower:
                offending_tables.append(f"{db_name}.{table_name}")
            continue

        # Apply only to direct table nodes (subquery aliases are not exp.Table).
        normalized = normalize_table_name(table_name, default_db)
        db_part, table_part = normalized.split(".", 1)
        table.set("db", exp.to_identifier(db_part))
        table.set("this", exp.to_identifier(table_part))
        changed = True

    if offending_tables:
        result["cross_db_violation"] = True
        result["offending_tables"] = offending_tables
        raise CrossDatabaseViolationError(offending_tables, default_db)

    if changed:
        result["normalized_sql"] = parsed.sql(dialect="clickhouse")
        result["normalization_applied"] = True

    return result


def normalize_sql_table_references(sql: str, default_db: str) -> str:
    detailed = normalize_sql_table_references_detailed(sql, default_db)
    return str(detailed.get("normalized_sql", sql))


__all__ = [
    "CrossDatabaseViolationError",
    "normalize_sql_table_references",
    "normalize_sql_table_references_detailed",
    "normalize_table_name",
]
