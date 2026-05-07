"""
SQL Guard Service

Enforces read-only SQL execution and workspace isolation.
CRITICAL SECURITY COMPONENT - Never skip validation.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Tuple

from query_api.utils import (
    CrossDatabaseViolationError,
    normalize_sql_table_references,
)

try:
    import sqlglot
    from sqlglot import exp
except Exception:  # pragma: no cover - guarded by tests in environment with dependency
    sqlglot = None
    exp = None
try:
    import sqlparse
except Exception:  # pragma: no cover
    sqlparse = None

logger = logging.getLogger(__name__)


def _allow_sqlglot_fallback() -> bool:
    value = str(os.getenv("ALLOW_SQLGLOT_FALLBACK", "false")).strip().lower()
    return value in {"1", "true", "yes", "on"}


class SQLGuard:
    """
    SQL Guard enforces:
    1. Read-only queries (SELECT/CTE SELECT only)
    2. Workspace database isolation
    3. No dangerous SQL operations
    4. Single-statement SQL
    """

    BLOCKED_KEYWORDS = [
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "ALTER",
        "TRUNCATE",
        "CREATE",
        "REPLACE",
        "GRANT",
        "REVOKE",
        "ATTACH",
        "DETACH",
        "OPTIMIZE",
        "SYSTEM",
        "KILL",
        "INTO OUTFILE",
        "INTO DUMPFILE",
    ]

    FAST_BLOCK_PATTERNS = [
        r";\s*\S",  # potential multi-statement
        r"--\s*",   # comment masking
        r"/\*",     # block comment
        r"\bINTO\s+OUTFILE\b",
        r"\bINTO\s+DUMPFILE\b",
    ]

    BLOCKED_TABLE_FUNCTIONS = {"file", "url"}

    def __init__(self, workspace_database=None):
        self.workspace_database = workspace_database

    def sanitize_sql(self, sql: str) -> str:
        try:
            sql = str(sql or "").strip()
            fence_match = re.search(r"```(?:sql)?\s*(.*?)\s*```", sql, flags=re.IGNORECASE | re.DOTALL)
            if fence_match:
                sql = fence_match.group(1).strip()
            sql = re.sub(r"^(?:sql\s*query|query|sql)\s*[:\-]\s*", "", sql, flags=re.IGNORECASE)
            select_like = re.search(r"\b(SELECT|WITH)\b", sql, flags=re.IGNORECASE)
            if select_like and select_like.start() > 0:
                sql = sql[select_like.start():]
            sql = re.sub(r"--.*?$", "", sql, flags=re.MULTILINE)
            sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
            sql = " ".join(sql.split())
            return sql.strip().rstrip(";")
        except Exception as exc:
            logger.error("SQL sanitization error: %s", exc)
            return (sql or "").strip()

    def enforce_workspace_database(self, sql: str) -> str:
        """Inject the workspace DB or reject cross-DB references.

        Phase 7 / CRIT-05: cross-database references must NEVER be silently
        passed through. ``CrossDatabaseViolationError`` is propagated so the
        caller can return HTTP 403 instead of executing tenant-foreign SQL.
        """

        if not self.workspace_database:
            return sql
        try:
            return normalize_sql_table_references(sql, self.workspace_database)
        except CrossDatabaseViolationError:
            # Re-raise so ``validate_and_sanitize`` can surface a stable
            # ``cross_db_violation`` error to the API view.
            raise
        except Exception as exc:
            logger.error("Failed to enforce workspace database: %s", exc)
            return sql

    def _parse_statements(self, sql: str) -> List[Any]:
        if sqlglot is None:
            raise RuntimeError("sqlglot is not installed")
        return sqlglot.parse(sql, read="clickhouse")

    def _sqlparse_validation(self, sql: str) -> Dict[str, Any]:
        if sqlparse is None:
            return {
                "allowed": False,
                "reason": "parser_unavailable",
                "blocked_keywords": [],
                "normalized_sql": "",
            }
        statements = [stmt for stmt in sqlparse.parse(sql) if str(stmt).strip()]
        if len(statements) != 1:
            return {
                "allowed": False,
                "reason": "multiple_statements_blocked",
                "blocked_keywords": [],
                "normalized_sql": "",
            }
        stmt_text = str(statements[0]).strip()
        if not stmt_text.upper().startswith(("SELECT", "WITH")):
            return {
                "allowed": False,
                "reason": "only_select_queries_allowed",
                "blocked_keywords": [],
                "normalized_sql": "",
            }
        upper_stmt = stmt_text.upper()
        blocked_found = []
        for keyword in self.BLOCKED_KEYWORDS:
            if re.search(r"\b" + re.escape(keyword) + r"\b", upper_stmt):
                blocked_found.append(keyword)
        if blocked_found:
            return {
                "allowed": False,
                "reason": "blocked_keyword_detected",
                "blocked_keywords": sorted(set(blocked_found)),
                "normalized_sql": "",
            }
        for fn in self.BLOCKED_TABLE_FUNCTIONS:
            if re.search(rf"\b{re.escape(fn)}\s*\(", stmt_text, re.IGNORECASE):
                return {
                    "allowed": False,
                    "reason": f"blocked_table_function:{fn}",
                    "blocked_keywords": [fn.upper()],
                    "normalized_sql": "",
                }
        return {
            "allowed": True,
            "reason": "ok_sqlparse",
            "blocked_keywords": [],
            "normalized_sql": " ".join(stmt_text.split()),
        }

    def _is_select_like(self, statement: Any) -> bool:
        if exp is None:
            return False
        if isinstance(statement, exp.Select):
            return True
        subqueryable_cls = getattr(exp, "Subqueryable", None)
        if subqueryable_cls is not None and isinstance(statement, subqueryable_cls):
            return True
        # sqlglot compatibility: some versions expose query roots as Query/Union/etc.
        if statement.__class__.__name__ in {"Query", "Union", "Except", "Intersect"}:
            return True
        if isinstance(statement, exp.With):
            if subqueryable_cls is not None:
                return isinstance(statement.this, subqueryable_cls)
            return isinstance(statement.this, exp.Select) or statement.this.__class__.__name__ in {
                "Query",
                "Union",
                "Except",
                "Intersect",
            }
        return False

    def _ast_validation(self, sql: str) -> Dict[str, Any]:
        if not sql:
            return {
                "allowed": False,
                "reason": "empty_sql",
                "blocked_keywords": [],
                "normalized_sql": "",
            }

        try:
            statements = self._parse_statements(sql)
        except Exception as exc:
            parser_missing = sqlglot is None or isinstance(exc, ModuleNotFoundError)
            if parser_missing and not _allow_sqlglot_fallback():
                return {
                    "allowed": False,
                    "reason": "sqlglot_unavailable",
                    "blocked_keywords": [],
                    "normalized_sql": "",
                }
            logger.warning("sqlglot parse unavailable/failed, falling back to sqlparse: %s", exc)
            return self._sqlparse_validation(sql)

        if not statements:
            return {
                "allowed": False,
                "reason": "parse_error:no_statement",
                "blocked_keywords": [],
                "normalized_sql": "",
            }

        if len(statements) != 1:
            return {
                "allowed": False,
                "reason": "multiple_statements_blocked",
                "blocked_keywords": [],
                "normalized_sql": "",
            }

        statement = statements[0]
        if not self._is_select_like(statement):
            return {
                "allowed": False,
                "reason": "only_select_queries_allowed",
                "blocked_keywords": [],
                "normalized_sql": "",
            }

        blocked_found: List[str] = []
        upper_sql = sql.upper()
        for keyword in self.BLOCKED_KEYWORDS:
            if re.search(r"\b" + re.escape(keyword) + r"\b", upper_sql):
                blocked_found.append(keyword)
        if blocked_found:
            return {
                "allowed": False,
                "reason": "blocked_keyword_detected",
                "blocked_keywords": sorted(set(blocked_found)),
                "normalized_sql": "",
            }

        # Explicit AST checks for write/admin operations.
        if exp is not None:
            forbidden_nodes = (
                exp.Insert,
                exp.Update,
                exp.Delete,
                exp.Create,
                exp.Drop,
                exp.Alter,
                exp.Command,
            )
            for node in statement.walk():
                if isinstance(node, forbidden_nodes):
                    return {
                        "allowed": False,
                        "reason": f"forbidden_ast_node:{node.key}",
                        "blocked_keywords": [node.key.upper()],
                        "normalized_sql": "",
                    }
                if isinstance(node, exp.Anonymous):
                    fn = str(node.name or "").strip().lower()
                    if fn in self.BLOCKED_TABLE_FUNCTIONS:
                        return {
                            "allowed": False,
                            "reason": f"blocked_table_function:{fn}",
                            "blocked_keywords": [fn.upper()],
                            "normalized_sql": "",
                        }

        # Workspace db isolation (when explicit database is provided in SQL).
        if self.workspace_database and exp is not None:
            expected_db = str(self.workspace_database).strip().lower()
            for table in statement.find_all(exp.Table):
                db_name = str(table.db or "").strip().strip("`").lower()
                if db_name and db_name != expected_db:
                    return {
                        "allowed": False,
                        "reason": f"database_mismatch:{db_name}",
                        "blocked_keywords": [],
                        "normalized_sql": "",
                    }

        normalized_sql = statement.sql(dialect="clickhouse")
        return {
            "allowed": True,
            "reason": "ok",
            "blocked_keywords": [],
            "normalized_sql": normalized_sql,
        }

    def validate_sql(self, sql: str) -> Tuple[bool, str, Dict]:
        sql_clean = (sql or "").strip()
        details: Dict[str, Any] = {
            "original_sql": sql or "",
            "checks_passed": [],
            "checks_failed": [],
            "blocked_keywords": [],
            "normalized_sql": "",
        }
        if not sql_clean:
            details["checks_failed"].append("SQL query is empty")
            return False, "SQL query is empty", details

        upper_sql = sql_clean.upper()
        for pattern in self.FAST_BLOCK_PATTERNS:
            if re.search(pattern, upper_sql, re.IGNORECASE):
                details["checks_failed"].append(f"fast_block_pattern:{pattern}")
                return False, "Dangerous SQL pattern detected", details
        details["checks_passed"].append("fast_precheck_passed")

        ast_result = self._ast_validation(sql_clean)
        details["blocked_keywords"] = ast_result.get("blocked_keywords", [])
        details["normalized_sql"] = ast_result.get("normalized_sql", "")
        if not ast_result.get("allowed"):
            details["checks_failed"].append(ast_result.get("reason", "ast_validation_failed"))
            return False, str(ast_result.get("reason", "SQL validation failed")), details
        details["checks_passed"].append("ast_validation_passed")
        return True, "SQL validation passed", details

    # Phase 6 / CRIT-05: the compiler emits a canonical
    # ``/* ch_settings: max_execution_time=60, ... */`` header on every
    # query. We strip it BEFORE the comment-masking check so the safety
    # check still rejects all other comments while letting the audited
    # settings header through.
    _CH_SETTINGS_HEADER_RE = re.compile(
        r"^\s*/\*\s*ch_settings\s*:.*?\*/\s*",
        flags=re.DOTALL | re.IGNORECASE,
    )

    def validate_and_sanitize(self, sql: str) -> Tuple[bool, str, str]:
        raw_sql = str(sql or "")
        raw_without_settings = self._CH_SETTINGS_HEADER_RE.sub("", raw_sql, count=1)
        if re.search(r"--\s*|/\*", raw_without_settings):
            return False, "SQL comments are not allowed", raw_sql.strip()
        sanitized = self.sanitize_sql(sql)
        is_valid, error_msg, details = self.validate_sql(sanitized)
        if not is_valid:
            return False, error_msg, sanitized

        parser_normalized = str(details.get("normalized_sql") or sanitized).strip()
        try:
            final_sql = self.enforce_workspace_database(parser_normalized)
        except CrossDatabaseViolationError as exc:
            return False, str(exc), parser_normalized
        return True, "Validation passed", final_sql


class SQLGuardFactory:
    @staticmethod
    def create_for_workspace(workspace) -> "SQLGuard":
        """Build a SQLGuard bound to the workspace's ClickHouse database.

        Per CRIT-05 the previous hardcoded ``workspace_database = "etl"`` was
        a tenant-isolation defect: every workspace shared a single namespace,
        so any user able to issue SQL against query-service could read every
        other tenant's data. ``workspace.clickhouse_db`` MUST be present;
        callers that pass a workspace without that attribute now fail loudly
        instead of silently routing to a wrong database.
        """

        if workspace is None:
            raise ValueError("workspace_is_required")
        db = getattr(workspace, "clickhouse_db", None)
        if not db:
            workspace_id = getattr(workspace, "id", None)
            raise ValueError(
                f"Workspace {workspace_id!r} has no clickhouse_db configured. "
                "Cannot create a safe SQL guard without a bound database."
            )
        return SQLGuard(workspace_database=str(db))

    @staticmethod
    def create_default():
        return SQLGuard()


def validate_sql(sql: str, workspace=None) -> Tuple[bool, str]:
    guard = SQLGuardFactory.create_for_workspace(workspace) if workspace else SQLGuardFactory.create_default()
    is_valid, error_msg, _ = guard.validate_and_sanitize(sql)
    return is_valid, error_msg


def sanitize_and_validate_sql(sql: str, workspace=None) -> Tuple[bool, str, str]:
    guard = SQLGuardFactory.create_for_workspace(workspace) if workspace else SQLGuardFactory.create_default()
    return guard.validate_and_sanitize(sql)
