from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from typing import Any

from preprocessing_high.preprocess_high_task import preprocess_high_task
from preprocessing_high.schemas import HighPreprocessConfig
from preprocessing_low.preprocess_task import preprocess_text_task

logger = logging.getLogger(__name__)

_NOISE_PATTERN = re.compile(
    r"\[(?:music|noise|background noise|silence|inaudible|unclear|crosstalk|applause|laughter|laughing|breathing|cough|sigh|unknown)\]"
    r"|<(?:unk|noise|silence|inaudible|laugh)>"
    r"|\b(?:uh+|um+|erm+|hmm+|mmm+|ah+|eh+|mm+|uh-huh|mm-hmm)\b",
    flags=re.IGNORECASE,
)
_REPEATED_WORD_PATTERN = re.compile(r"\b(\w+)(?:\s+\1\b)+", flags=re.IGNORECASE)
_TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", flags=re.UNICODE)
_MAX_LOW_CHANGES = 20


def _default_preprocessing_low(text: str) -> dict[str, Any]:
    normalized_text = str(text or "")
    return {
        "original_text": normalized_text,
        "cleaned_text": normalized_text,
        "spelling_corrected_text": normalized_text,
        "spelling_changes": [],
        "has_spelling_correction": False,
        "removed_filler_words": [],
        "changes": {"spelling_corrections": [], "removed_filler_words": []},
        "correction_source": "",
    }


def _default_preprocessing_high(corrected_query: str = "") -> dict[str, Any]:
    return {
        "corrected_query": str(corrected_query or ""),
        "term_corrections": [],
        "schema_used": {"tables": [], "columns": []},
        "schema_adjustments": [],
    }


def _tokenize(text: str) -> list[str]:
    return _TOKEN_PATTERN.findall(str(text or ""))


def _join_tokens(tokens: list[str]) -> str:
    if not tokens:
        return ""
    text = " ".join(tokens)
    text = re.sub(r"\s+([,.;:!?%])", r"\1", text)
    text = re.sub(r"([\(\[\{])\s+", r"\1", text)
    text = re.sub(r"\s+([\)\]\}])", r"\1", text)
    return text.strip()


def _classify_low_change(before: str, after: str) -> str:
    before_text = str(before or "").strip()
    after_text = str(after or "").strip()
    if _NOISE_PATTERN.search(before_text):
        return "removed_noise"
    if _REPEATED_WORD_PATTERN.search(before_text):
        return "reduced_repetition"
    if not after_text and len(before_text.split()) >= 2:
        return "removed_noise"
    return "normalized"


def _build_low_changes(original_text: str, cleaned_text: str) -> list[dict[str, str]]:
    before_tokens = _tokenize(original_text)
    after_tokens = _tokenize(cleaned_text)
    if not before_tokens and not after_tokens:
        return []

    matcher = SequenceMatcher(
        a=[token.lower() for token in before_tokens],
        b=[token.lower() for token in after_tokens],
        autojunk=False,
    )
    changes: list[dict[str, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        before_chunk = _join_tokens(before_tokens[i1:i2])
        after_chunk = _join_tokens(after_tokens[j1:j2])
        if not before_chunk and not after_chunk:
            continue
        changes.append(
            {
                "type": _classify_low_change(before_chunk, after_chunk),
                "before": before_chunk,
                "after": after_chunk,
            }
        )
        if len(changes) >= _MAX_LOW_CHANGES:
            break

    if not changes and original_text.strip() != cleaned_text.strip():
        changes.append(
            {
                "type": "normalized",
                "before": original_text.strip(),
                "after": cleaned_text.strip(),
            }
        )
    return changes


def _extract_schema_used(raw_schema: Any) -> dict[str, list[str]]:
    if not isinstance(raw_schema, dict):
        return {"tables": [], "columns": []}

    tables = raw_schema.get("tables", [])
    tables_list = [str(table) for table in tables if str(table or "").strip()]

    columns_payload = raw_schema.get("columns", {})
    flattened_columns: list[str] = []
    if isinstance(columns_payload, dict):
        for table_name, columns in columns_payload.items():
            normalized_table = str(table_name or "").strip()
            if not isinstance(columns, list):
                continue
            for column in columns:
                if isinstance(column, dict):
                    column_name = str(column.get("name", "")).strip()
                else:
                    column_name = str(column or "").strip()
                if not column_name:
                    continue
                if normalized_table:
                    flattened_columns.append(f"{normalized_table}.{column_name}")
                else:
                    flattened_columns.append(column_name)
    elif isinstance(columns_payload, list):
        flattened_columns = [str(column) for column in columns_payload if str(column or "").strip()]

    return {
        "tables": tables_list,
        "columns": flattened_columns,
    }


def _extract_term_corrections(mappings: Any) -> list[dict[str, str]]:
    if not isinstance(mappings, list):
        return []

    corrections: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        status = str(mapping.get("status", "")).strip().lower()
        requested = str(mapping.get("requested", "")).strip()
        matched_column = str(mapping.get("matched_column", "")).strip()
        matched_table = str(mapping.get("matched_table", "")).strip()
        if status not in {"exact", "mapped", "derivable"}:
            continue
        if not requested or not matched_column:
            continue
        if status == "exact" and requested.lower() == matched_column.lower():
            continue
        fully_qualified = (
            f"{matched_table}.{matched_column}" if matched_table else matched_column
        )
        signature = (requested.lower(), matched_column.lower(), fully_qualified.lower())
        if signature in seen:
            continue
        seen.add(signature)
        corrections.append(
            {
                "original": requested,
                "corrected": matched_column,
                "matched_column": fully_qualified,
            }
        )
    return corrections


def _extract_schema_adjustments(mappings: Any) -> list[dict[str, str]]:
    if not isinstance(mappings, list):
        return []

    adjustments: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        status = str(mapping.get("status", "")).strip().lower()
        requested = str(mapping.get("requested", "")).strip()
        matched_column = str(mapping.get("matched_column", "")).strip()
        matched_table = str(mapping.get("matched_table", "")).strip()
        if status not in {"mapped", "derivable"}:
            continue

        fully_qualified = (
            f"{matched_table}.{matched_column}" if matched_table and matched_column else matched_column
        )
        if status == "mapped":
            adjustment_type = "mapped_column"
            description = f"Mapped '{requested}' to '{fully_qualified or matched_column}'."
        else:
            adjustment_type = "derived_field"
            description = f"Derived '{requested}' from '{fully_qualified or matched_column}'."

        signature = (adjustment_type, description)
        if signature in seen:
            continue
        seen.add(signature)
        adjustments.append({"type": adjustment_type, "description": description})
    return adjustments


def _build_preprocessing_high_payload(
    preprocess_high_result: dict[str, Any] | None,
    *,
    fallback_query: str,
) -> dict[str, Any]:
    if not isinstance(preprocess_high_result, dict):
        return _default_preprocessing_high(corrected_query=fallback_query)

    corrected_query = str(
        preprocess_high_result.get("final_query")
        or preprocess_high_result.get("corrected_query")
        or fallback_query
        or ""
    )
    mappings = preprocess_high_result.get("mappings", [])
    schema_used = _extract_schema_used(preprocess_high_result.get("schema_used"))
    return {
        "corrected_query": corrected_query,
        "term_corrections": _extract_term_corrections(mappings),
        "schema_used": schema_used,
        "schema_adjustments": _extract_schema_adjustments(mappings),
    }


def build_preprocessing_metadata(
    text: str,
    *,
    user_id: str | None = None,
    run_high: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    source_text = str(text or "").strip()
    low_payload = _default_preprocessing_low(source_text)
    high_payload = _default_preprocessing_high(source_text)

    if not source_text:
        return low_payload, high_payload

    preprocess_low_result: dict[str, Any] | None = None
    try:
        preprocess_low_result = preprocess_text_task.fn(text=source_text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Low preprocessing transparency failed: %s", exc)

    cleaned_text = source_text
    detected_changes: list[dict[str, str]] = []
    if isinstance(preprocess_low_result, dict) and preprocess_low_result.get("status") == "success":
        cleaned_text = str(preprocess_low_result.get("cleaned_text") or source_text).strip() or source_text
        raw_changes = preprocess_low_result.get("detected_changes", [])
        if isinstance(raw_changes, list):
            detected_changes = [
                {
                    "type": str(change.get("type", "")).strip(),
                    "before": str(change.get("before", "")).strip(),
                    "after": str(change.get("after", "")).strip(),
                }
                for change in raw_changes
                if isinstance(change, dict)
            ]
            detected_changes = [change for change in detected_changes if any(change.values())]

    low_payload = {
        "original_text": source_text,
        "cleaned_text": cleaned_text,
        "spelling_corrected_text": str(preprocess_low_result.get("spelling_corrected_text") or source_text)
        if isinstance(preprocess_low_result, dict)
        else source_text,
        "spelling_changes": (
            [
                {
                    "original": str(change.get("original", "")).strip(),
                    "corrected": str(change.get("corrected", "")).strip(),
                }
                for change in preprocess_low_result.get("spelling_changes", [])
                if isinstance(change, dict)
            ]
            if isinstance(preprocess_low_result, dict)
            else []
        ),
        "has_spelling_correction": bool(preprocess_low_result.get("has_spelling_correction"))
        if isinstance(preprocess_low_result, dict)
        else False,
        "removed_filler_words": (
            [str(item) for item in preprocess_low_result.get("removed_filler_words", []) if str(item).strip()]
            if isinstance(preprocess_low_result, dict)
            else []
        ),
        "changes": (
            preprocess_low_result.get("changes", {})
            if isinstance(preprocess_low_result, dict) and isinstance(preprocess_low_result.get("changes"), dict)
            else {
                "spelling_corrections": [],
                "removed_filler_words": (
                    [change.get("before", "") for change in detected_changes if change.get("type") == "removed_filler_words"]
                ),
            }
        ),
        "correction_source": str(preprocess_low_result.get("correction_source", ""))
        if isinstance(preprocess_low_result, dict)
        else "",
        "detected_changes": detected_changes or _build_low_changes(source_text, cleaned_text),
    }

    if not run_high:
        return low_payload, _default_preprocessing_high(corrected_query=cleaned_text)

    preprocess_high_result: dict[str, Any] | None = None
    try:
        resolved_user_id = str(user_id or "").strip() or HighPreprocessConfig.from_env().default_user_id
        preprocess_high_result = preprocess_high_task.fn(
            cleaned_text=cleaned_text,
            user_id=resolved_user_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("High preprocessing transparency failed: %s", exc)

    high_payload = _build_preprocessing_high_payload(
        preprocess_high_result,
        fallback_query=cleaned_text,
    )
    return low_payload, high_payload
