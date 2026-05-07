"""
Shared SQL normalization primitives.
"""

from __future__ import annotations
import re


_CH_SETTINGS_PREFIX_RE = re.compile(
    r"^\s*/\*\s*ch_settings\s*:[\s\S]*?\*/\s*",
    flags=re.IGNORECASE,
)


def sanitize_sql_for_metabase(sql: str) -> str:
    """
    Normalize SQL formatting for Metabase native-query compatibility.

    Rules:
    - Trim surrounding whitespace.
    - Remove a leading ``/* ch_settings: ... */`` transport header.
    - Remove one or more trailing semicolons.
    - Preserve SQL content and internal formatting.
    """

    normalized = str(sql or "").strip()
    normalized = _CH_SETTINGS_PREFIX_RE.sub("", normalized, count=1)
    while normalized.endswith(";"):
        normalized = normalized[:-1].rstrip()
    return normalized
