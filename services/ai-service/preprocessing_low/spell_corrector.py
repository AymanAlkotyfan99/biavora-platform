from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Callable


_WORD_PATTERN = re.compile(r"\b\w+\b", flags=re.UNICODE)
_SNAKE_CASE_PATTERN = re.compile(r"^[a-zA-Z]+(?:_[a-zA-Z0-9]+)+$")
_SQL_KEYWORDS = {
    "select",
    "from",
    "where",
    "join",
    "left",
    "right",
    "inner",
    "outer",
    "group",
    "by",
    "order",
    "having",
    "limit",
    "offset",
    "insert",
    "update",
    "delete",
    "create",
    "alter",
    "drop",
    "table",
    "column",
    "values",
    "into",
    "as",
    "and",
    "or",
    "not",
    "null",
    "distinct",
    "count",
    "sum",
    "avg",
    "min",
    "max",
}
_PUNCT_TRIM = ".,!?;:()[]{}\"'"
_PROTECTED_ANALYTICAL_KEYWORDS = {
    "highest",
    "lowest",
    "top",
    "bottom",
    "best",
    "worst",
    "maximum",
    "minimum",
    "trend",
    "relationship",
    "compare",
    "forecast",
    "predict",
    "most",
    "least",
}
_PROTECTED_ANALYTICAL_PHRASES = {"over time", "per day", "per week"}


@dataclass(frozen=True)
class SpellingCorrectionResult:
    text: str
    changes: list[dict[str, str]]
    has_correction: bool
    skipped_reason: str


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _word_tokens(text: str) -> list[str]:
    return _WORD_PATTERN.findall(str(text or ""))


def _is_protected_token(token: str) -> bool:
    value = str(token or "").strip(_PUNCT_TRIM)
    if not value:
        return False
    lowered = value.lower()
    if lowered in _SQL_KEYWORDS:
        return True
    if _SNAKE_CASE_PATTERN.fullmatch(value):
        return True
    if "." in value:
        return True
    if any(ch.isdigit() for ch in value):
        return True
    return False


def _has_protected_token_changes(original: str, corrected: str) -> bool:
    original_tokens = str(original or "").split()
    corrected_tokens = str(corrected or "").split()
    protected_before = [token for token in original_tokens if _is_protected_token(token)]
    protected_after = [token for token in corrected_tokens if _is_protected_token(token)]
    if len(protected_before) != len(protected_after):
        return True
    for before, after in zip(protected_before, protected_after):
        before_clean = before.strip(_PUNCT_TRIM)
        after_clean = after.strip(_PUNCT_TRIM)
        if before_clean.lower() != after_clean.lower():
            return True
    return False


def _build_spelling_prompt(text: str) -> str:
    return (
        "Correct only spelling mistakes in the user question.\n"
        "Do not rephrase.\n"
        "Do not change the meaning.\n"
        "Do not remove analytical keywords.\n"
        "Do not remove words like highest, lowest, top, trend, relationship, forecast, compare.\n"
        "Do not change snake_case database tokens.\n"
        "Return only the corrected sentence.\n\n"
        f"Input:\n{text}\n\n"
        "Output:"
    )


def correct_spelling_llm(text: str, llm_client: Callable[[str], str]) -> str:
    prompt = _build_spelling_prompt(text)
    corrected = llm_client(prompt)
    return _normalize_whitespace(corrected)


def detect_spelling_changes(original: str, corrected: str) -> list[dict[str, str]]:
    before_words = _word_tokens(original)
    after_words = _word_tokens(corrected)
    if not before_words and not after_words:
        return []

    matcher = SequenceMatcher(
        a=[word.lower() for word in before_words],
        b=[word.lower() for word in after_words],
        autojunk=False,
    )
    changes: list[dict[str, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag != "replace":
            continue
        left = before_words[i1:i2]
        right = after_words[j1:j2]
        for left_token, right_token in zip(left, right):
            if left_token.lower() == right_token.lower():
                continue
            changes.append({"original": left_token, "corrected": right_token})
    return changes


def _tokenize_words_preserve_case(text: str) -> list[str]:
    return _word_tokens(text)


def _token_set_lower(text: str) -> set[str]:
    return {token.lower() for token in _tokenize_words_preserve_case(text)}


def _has_protected_keyword_removal(original: str, corrected: str) -> bool:
    original_tokens = _token_set_lower(original)
    corrected_tokens = _token_set_lower(corrected)
    for keyword in _PROTECTED_ANALYTICAL_KEYWORDS:
        if keyword in original_tokens and keyword not in corrected_tokens:
            return True

    original_lower = str(original or "").lower()
    corrected_lower = str(corrected or "").lower()
    for phrase in _PROTECTED_ANALYTICAL_PHRASES:
        if phrase in original_lower and phrase not in corrected_lower:
            return True
    return False


def _snake_case_tokens(text: str) -> list[str]:
    return [token for token in str(text or "").split() if _SNAKE_CASE_PATTERN.fullmatch(token.strip(_PUNCT_TRIM))]


def _snake_case_changed(original: str, corrected: str) -> bool:
    original_tokens = _snake_case_tokens(original)
    corrected_tokens = _snake_case_tokens(corrected)
    if len(original_tokens) != len(corrected_tokens):
        return True
    return any(left != right for left, right in zip(original_tokens, corrected_tokens))


def _token_change_ratio(original: str, corrected: str) -> float:
    before_words = _word_tokens(original)
    after_words = _word_tokens(corrected)
    if not before_words:
        return 0.0
    matcher = SequenceMatcher(
        a=[word.lower() for word in before_words],
        b=[word.lower() for word in after_words],
        autojunk=False,
    )
    changed = 0
    for tag, i1, i2, _j1, _j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        changed += (i2 - i1)
    return changed / max(1, len(before_words))


def _has_unrelated_additions(original: str, corrected: str, changes: list[dict[str, str]]) -> bool:
    before_words = [word.lower() for word in _word_tokens(original)]
    after_words = [word.lower() for word in _word_tokens(corrected)]
    if len(after_words) <= len(before_words):
        return False
    before_set = set(before_words)
    changed_targets = {str(change.get("corrected", "")).lower() for change in changes}
    for token in after_words:
        if token in before_set or token in changed_targets or token in _PROTECTED_ANALYTICAL_KEYWORDS:
            continue
        if _is_protected_token(token):
            continue
        return True
    return False


def _is_high_confidence_typo_changes(changes: list[dict[str, str]]) -> bool:
    if not changes:
        return False
    for change in changes:
        original = str(change.get("original", "")).strip().lower()
        corrected = str(change.get("corrected", "")).strip().lower()
        if not original or not corrected:
            return False
        if any(ch.isdigit() for ch in original + corrected):
            return False
        if abs(len(original) - len(corrected)) > 2:
            return False
        if SequenceMatcher(a=original, b=corrected, autojunk=False).ratio() < 0.7:
            return False
    return True


def apply_spelling_correction(
    text: str,
    llm_client: Callable[[str], str],
) -> SpellingCorrectionResult:
    original_text = str(text or "")
    original_words = _word_tokens(original_text)
    if len(original_words) < 3:
        return SpellingCorrectionResult(
            text=original_text,
            changes=[],
            has_correction=False,
            skipped_reason="short_text",
        )

    try:
        corrected_text = correct_spelling_llm(original_text, llm_client)
    except Exception:  # noqa: BLE001
        return SpellingCorrectionResult(
            text=original_text,
            changes=[],
            has_correction=False,
            skipped_reason="llm_error",
        )

    if not corrected_text:
        return SpellingCorrectionResult(
            text=original_text,
            changes=[],
            has_correction=False,
            skipped_reason="empty_output",
        )

    if _normalize_whitespace(original_text) == corrected_text:
        return SpellingCorrectionResult(
            text=original_text,
            changes=[],
            has_correction=False,
            skipped_reason="no_change",
        )

    if _has_protected_token_changes(original_text, corrected_text):
        return SpellingCorrectionResult(
            text=original_text,
            changes=[],
            has_correction=False,
            skipped_reason="protected_token_changed",
        )

    spelling_changes = detect_spelling_changes(original_text, corrected_text)
    if not spelling_changes:
        return SpellingCorrectionResult(
            text=original_text,
            changes=[],
            has_correction=False,
            skipped_reason="no_word_level_change",
        )

    changed_ratio = _token_change_ratio(original_text, corrected_text)
    if changed_ratio > 0.4 and not _is_high_confidence_typo_changes(spelling_changes):
        return SpellingCorrectionResult(
            text=original_text,
            changes=[],
            has_correction=False,
            skipped_reason="too_many_changes",
        )
    if _has_protected_keyword_removal(original_text, corrected_text):
        return SpellingCorrectionResult(
            text=original_text,
            changes=[],
            has_correction=False,
            skipped_reason="protected_keyword_removed",
        )
    if _snake_case_changed(original_text, corrected_text):
        return SpellingCorrectionResult(
            text=original_text,
            changes=[],
            has_correction=False,
            skipped_reason="snake_case_changed",
        )
    if _has_unrelated_additions(original_text, corrected_text, spelling_changes):
        return SpellingCorrectionResult(
            text=original_text,
            changes=[],
            has_correction=False,
            skipped_reason="unrelated_additions",
        )
    if not _is_high_confidence_typo_changes(spelling_changes):
        return SpellingCorrectionResult(
            text=original_text,
            changes=[],
            has_correction=False,
            skipped_reason="low_confidence_changes",
        )

    return SpellingCorrectionResult(
        text=corrected_text,
        changes=spelling_changes,
        has_correction=True,
        skipped_reason="",
    )
