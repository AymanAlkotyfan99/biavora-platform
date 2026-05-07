from __future__ import annotations

import re

try:
    import sqlglot
    from sqlglot import exp
except Exception:  # pragma: no cover
    sqlglot = None
    exp = None


def normalize_table_name(table_name: str, default_db: str) -> str:
    """
    Normalize table names to ClickHouse-safe form.

    Rules:
    - no dot -> default_db.table
    - exactly one dot -> keep as is
    - multiple dots -> keep only the last two parts
    """
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


def normalize_sql_table_references(sql: str, default_db: str) -> str:
    """
    Normalize physical table references in SELECT/WITH SQL without rewriting CTE aliases.
    """
    if not sql or not sql.strip() or not default_db or not default_db.strip():
        return sql
    if sqlglot is None or exp is None:
        cte_names = {
            match.group(1).strip("`").lower()
            for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s+AS\s*\(", sql, flags=re.IGNORECASE)
        }

        def _replace(match: re.Match) -> str:
            clause = match.group(1)
            raw_table = match.group(2)
            table_name = raw_table.strip("`")
            if table_name.lower() in cte_names or "." in table_name:
                return match.group(0)
            return f"{clause} {normalize_table_name(table_name, default_db)}"

        return re.sub(
            r"\b(FROM|JOIN)\s+(`?[A-Za-z_][A-Za-z0-9_\.]*`?)",
            _replace,
            sql,
            flags=re.IGNORECASE,
        )

    parsed = sqlglot.parse_one(sql, read="clickhouse")
    if parsed is None:
        return sql

    cte_names = {
        str(getattr(cte, "alias_or_name", "") or "").strip().strip("`").lower()
        for cte in parsed.find_all(exp.CTE)
        if str(getattr(cte, "alias_or_name", "") or "").strip()
    }

    changed = False
    for table in parsed.find_all(exp.Table):
        db_name = str(table.db or "").strip().strip("`")
        table_name = str(table.name or "").strip().strip("`")
        if not table_name or db_name or table_name.lower() in cte_names:
            continue
        db_part, table_part = normalize_table_name(table_name, default_db).split(".", 1)
        table.set("db", exp.to_identifier(db_part))
        table.set("this", exp.to_identifier(table_part))
        changed = True

    return parsed.sql(dialect="clickhouse") if changed else sql
