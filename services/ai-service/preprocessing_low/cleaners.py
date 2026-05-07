from __future__ import annotations

import re
from difflib import get_close_matches


_NOISE_TAG_PATTERN = re.compile(
    r"\[(?:music|noise|background noise|silence|inaudible|unclear|crosstalk|applause|laughter|laughing|breathing|cough|sigh|unknown)\]",
    flags=re.IGNORECASE,
)
_NOISE_TOKEN_PATTERN = re.compile(
    r"<(?:unk|noise|silence|inaudible|laugh)>",
    flags=re.IGNORECASE,
)
_HESITATION_PATTERN = re.compile(
    r"\b(?:uh+|um+|erm+|hmm+|mmm+|ah+|eh+|mm+|uh-huh|mm-hmm)\b",
    flags=re.IGNORECASE,
)
_FILLER_PATTERN = re.compile(
    r"\b(?:like|you know|i mean|sort of|kind of|basically|actually|please)\b",
    flags=re.IGNORECASE,
)
_GREETING_LEADING_PATTERN = re.compile(
    r"^\s*(?:hi|hello|hey)\b[\s,!?-]*",
    flags=re.IGNORECASE,
)
_POLITE_LEADING_PATTERN = re.compile(
    r"^\s*(?:can you|could you|show me)\b[\s,!?-]*",
    flags=re.IGNORECASE,
)
_POLITE_TRAILING_PATTERN = re.compile(
    r"[\s,!?-]*(?:please)\s*$",
    flags=re.IGNORECASE,
)
_DUPLICATE_WORD_PATTERN = re.compile(r"\b(\w+)(?:\s+\1\b)+", flags=re.IGNORECASE)
_EXCESSIVE_PUNCTUATION_PATTERN = re.compile(r"([!?.,;:])\1+")
_CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x1F\x7F]")
_MALFORMED_SYMBOL_PATTERN = re.compile(r"(?:\uFFFD)+")
_PUNCT_ONLY_PATTERN = re.compile(r"^[\W_]+$", flags=re.UNICODE)
_NUMERIC_ONLY_PATTERN = re.compile(r"^[\d\s,._-]+$")
_NOISE_ONLY_PATTERN = re.compile(
    r"^(?:uh+|um+|umm+|uhh+|erm+|hmm+|mmm+|ah+|eh+|mm+|like|please|you\s+know)(?:\s+(?:uh+|um+|umm+|uhh+|erm+|hmm+|mmm+|ah+|eh+|mm+|like|please|you\s+know))*$",
    flags=re.IGNORECASE,
)
_EMPTY_LIKE_PATTERN = re.compile(
    r"^(?:\s|[^\w]|uh+|um+|erm+|hmm+|mmm+|ah+|eh+|mm+|uh-huh|mm-hmm|like|you know|please)+$",
    flags=re.IGNORECASE,
)
_TOKEN_PATTERN = re.compile(r"\b[a-zA-Z][a-zA-Z_]{2,}\b")
_ALPHA_TOKEN_PATTERN = re.compile(r"\b[A-Za-z]{8,}\b")

_BOUNDARY_HINT_TOKENS = {
    "show",
    "list",
    "display",
    "give",
    "get",
    "top",
    "bottom",
    "total",
    "sum",
    "average",
    "avg",
    "count",
    "number",
    "numbers",
    "by",
    "per",
    "for",
    "from",
    "with",
    "where",
    "group",
    "grouped",
    "across",
    "between",
    "and",
    "or",
    "in",
    "on",
    "of",
    "year",
    "years",
    "month",
    "months",
    "day",
    "days",
    "week",
    "weeks",
    "quarter",
    "quarters",
    "date",
    "time",
    "region",
    "city",
    "country",
    "state",
    "population",
    "sales",
    "revenue",
    "profit",
    "margin",
    "trend",
    "breakdown",
    "distribution",
}

_SPELLING_LEXICON = {
    "show",
    "list",
    "display",
    "give",
    "total",
    "sum",
    "average",
    "avg",
    "count",
    "number",
    "total",
    "top",
    "bottom",
    "highest",
    "lowest",
    "maximum",
    "minimum",
    "population",
    "region",
    "city",
    "country",
    "state",
    "year",
    "month",
    "date",
    "revenue",
    "profit",
    "margin",
    "sales",
    "customer",
    "customers",
    "order",
    "orders",
    "trend",
    "distribution",
    "breakdown",
    "compare",
    "across",
    "group",
    "grouped",
    "quarter",
    "daily",
    "weekly",
    "monthly",
}
_BOUNDARY_LEXICON = _SPELLING_LEXICON | _BOUNDARY_HINT_TOKENS


def _collect_matches(pattern: re.Pattern[str], text: str) -> list[str]:
    return [match.group(0).strip() for match in pattern.finditer(text or "") if match.group(0).strip()]


def _append_change(changes: list[dict[str, str]], *, change_type: str, before: str, after: str) -> None:
    before_text = str(before or "").strip()
    after_text = str(after or "").strip()
    if not before_text and not after_text:
        return
    changes.append({"type": change_type, "before": before_text, "after": after_text})


def _reduce_repeated_characters(text: str, max_repeats: int = 2) -> str:
    pattern = re.compile(r"([^0-9\s])\1{2,}")
    return pattern.sub(lambda match: match.group(1) * max_repeats, text)


def _normalize_casing(text: str) -> str:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return text
    uppercase_ratio = sum(1 for ch in letters if ch.isupper()) / len(letters)
    if uppercase_ratio >= 0.7:
        return text.lower()
    return text


def _singular_variants(token: str) -> set[str]:
    normalized = str(token or "").strip().lower()
    if not normalized:
        return set()
    variants: set[str] = set()
    if normalized.endswith("ies") and len(normalized) > 4:
        variants.add(normalized[:-3] + "y")
    if (
        normalized.endswith("s")
        and len(normalized) > 3
        and not normalized.endswith(("ss", "us", "is", "ous"))
    ):
        variants.add(normalized[:-1])
    return variants


def _is_boundary_known_piece(token: str) -> bool:
    normalized = str(token or "").strip().lower()
    if not normalized:
        return False
    if normalized in _BOUNDARY_LEXICON:
        return True
    if any(variant in _BOUNDARY_LEXICON for variant in _singular_variants(normalized)):
        return True
    fuzzy = get_close_matches(normalized, list(_BOUNDARY_LEXICON), n=1, cutoff=0.9)
    return bool(fuzzy)


def _segment_alpha_token(token: str) -> list[str]:
    normalized = str(token or "")
    if not normalized.isalpha():
        return [normalized]
    lowered = normalized.lower()
    if len(lowered) < 8 or lowered in _BOUNDARY_LEXICON:
        return [normalized]

    n = len(lowered)
    max_piece_len = 20
    split_penalty = 0.35

    def _piece_score(piece: str) -> float:
        if _is_boundary_known_piece(piece):
            return 2.6
        if len(piece) <= 2:
            return -3.0
        if len(piece) == 3:
            return -1.4
        return -0.6

    best_scores = [-10_000.0] * (n + 1)
    best_paths: list[list[int]] = [[] for _ in range(n + 1)]
    best_scores[n] = 0.0

    for i in range(n - 1, -1, -1):
        upper = min(n, i + max_piece_len)
        for j in range(i + 2, upper + 1):
            piece = lowered[i:j]
            score = _piece_score(piece) + best_scores[j]
            if j < n:
                score -= split_penalty
            if score > best_scores[i]:
                best_scores[i] = score
                best_paths[i] = [j] + best_paths[j]

    if not best_paths[0]:
        return [normalized]

    boundaries = [0] + best_paths[0]
    segments = [
        normalized[boundaries[idx] : boundaries[idx + 1]]
        for idx in range(len(boundaries) - 1)
        if boundaries[idx + 1] > boundaries[idx]
    ]
    lowered_segments = [segment.lower() for segment in segments]
    known_count = sum(1 for segment in lowered_segments if _is_boundary_known_piece(segment))
    unknown_segments = [segment for segment in lowered_segments if not _is_boundary_known_piece(segment)]
    baseline_score = _piece_score(lowered)

    if len(segments) < 2:
        return [normalized]
    if known_count < 2:
        return [normalized]
    if any(len(segment) < 4 for segment in unknown_segments):
        return [normalized]
    if best_scores[0] <= baseline_score + 0.9:
        return [normalized]
    return segments


def _repair_token_boundaries(text: str) -> tuple[str, list[dict[str, str]]]:
    if not text:
        return text, []

    repaired = str(text)
    changes: list[dict[str, str]] = []

    boundary_passes = [
        re.compile(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])"),
        re.compile(r"(?<=[a-z])(?=[A-Z])"),
        re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])"),
    ]
    for pattern in boundary_passes:
        updated = pattern.sub(" ", repaired)
        if updated != repaired:
            changes.append(
                {
                    "type": "repaired_token_boundaries",
                    "before": repaired,
                    "after": updated,
                }
            )
            repaired = updated

    def _segment_match(match: re.Match[str]) -> str:
        token = match.group(0)
        segmented = _segment_alpha_token(token)
        if len(segmented) <= 1:
            return token
        replacement = " ".join(segmented)
        if replacement != token:
            changes.append(
                {
                    "type": "repaired_token_boundaries",
                    "before": token,
                    "after": replacement,
                }
            )
        return replacement

    repaired = _ALPHA_TOKEN_PATTERN.sub(_segment_match, repaired)
    compact = re.sub(r"\s+", " ", repaired).strip()
    if compact != repaired:
        repaired = compact
    return repaired, changes


def _conservative_spelling_correction(text: str) -> tuple[str, list[dict[str, str]]]:
    changes: list[dict[str, str]] = []
    if not text:
        return text, changes

    def _replace(match: re.Match[str]) -> str:
        token = match.group(0)
        token_lower = token.lower()

        if "_" in token_lower or any(ch.isdigit() for ch in token_lower):
            return token
        if token_lower in _SPELLING_LEXICON:
            return token
        if len(token_lower) < 4:
            return token

        matches = get_close_matches(token_lower, list(_SPELLING_LEXICON), n=1, cutoff=0.8)
        if not matches:
            return token

        corrected = matches[0]
        if corrected == token_lower:
            return token

        replacement = corrected
        if token[0].isupper():
            replacement = corrected.capitalize()

        changes.append(
            {
                "type": "corrected_spelling",
                "before": token,
                "after": replacement,
            }
        )
        return replacement

    corrected_text = _TOKEN_PATTERN.sub(_replace, text)
    return corrected_text, changes


def _is_numeric_only_input(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    return bool(_NUMERIC_ONLY_PATTERN.fullmatch(normalized) and re.search(r"\d", normalized))


def _is_noise_like_input(text: str) -> bool:
    normalized = re.sub(r"[^\w\s]", " ", str(text or "").lower())
    compact = re.sub(r"\s+", " ", normalized).strip()
    if not compact:
        return False
    return bool(_NOISE_ONLY_PATTERN.fullmatch(compact))


def _rule_based_clean_with_changes(text: str) -> tuple[str, list[dict[str, str]], dict[str, bool]]:
    source_text = str(text or "")
    cleaned = source_text.replace("\u200e", " ").replace("\u200f", " ")
    changes: list[dict[str, str]] = []

    if cleaned != source_text:
        _append_change(changes, change_type="normalized_control_chars", before=source_text, after=cleaned)

    for pattern in (_GREETING_LEADING_PATTERN, _POLITE_LEADING_PATTERN):
        match = pattern.search(cleaned)
        if match:
            removed = match.group(0).strip()
            if removed:
                _append_change(
                    changes,
                    change_type="removed_filler_words",
                    before=removed,
                    after="",
                )
            cleaned = pattern.sub("", cleaned, count=1)

    for pattern, change_type in (
        (_CONTROL_CHARS_PATTERN, "removed_control_chars"),
        (_MALFORMED_SYMBOL_PATTERN, "removed_malformed_symbols"),
        (_NOISE_TAG_PATTERN, "removed_noise_tags"),
        (_NOISE_TOKEN_PATTERN, "removed_noise_tokens"),
        (_HESITATION_PATTERN, "removed_filler_words"),
        (_FILLER_PATTERN, "removed_filler_words"),
    ):
        matched = _collect_matches(pattern, cleaned)
        if matched:
            _append_change(
                changes,
                change_type=change_type,
                before=", ".join(matched),
                after="",
            )
            cleaned = pattern.sub(" ", cleaned)

    trailing_polite_match = _POLITE_TRAILING_PATTERN.search(cleaned)
    if trailing_polite_match:
        removed = trailing_polite_match.group(0).strip()
        if removed:
            _append_change(
                changes,
                change_type="removed_filler_words",
                before=removed,
                after="",
            )
        cleaned = _POLITE_TRAILING_PATTERN.sub("", cleaned, count=1)

    repeated_chars_cleaned = _reduce_repeated_characters(cleaned, max_repeats=2)
    if repeated_chars_cleaned != cleaned:
        _append_change(
            changes,
            change_type="normalized_repeated_characters",
            before=cleaned,
            after=repeated_chars_cleaned,
        )
        cleaned = repeated_chars_cleaned

    deduped_cleaned = _DUPLICATE_WORD_PATTERN.sub(r"\1", cleaned)
    if deduped_cleaned != cleaned:
        _append_change(
            changes,
            change_type="reduced_repetition",
            before=cleaned,
            after=deduped_cleaned,
        )
        cleaned = deduped_cleaned

    punctuation_cleaned = _EXCESSIVE_PUNCTUATION_PATTERN.sub(r"\1", cleaned)
    if punctuation_cleaned != cleaned:
        _append_change(
            changes,
            change_type="normalized_punctuation",
            before=cleaned,
            after=punctuation_cleaned,
        )
        cleaned = punctuation_cleaned

    boundary_repaired, boundary_changes = _repair_token_boundaries(cleaned)
    if boundary_repaired != cleaned:
        _append_change(
            changes,
            change_type="repaired_token_boundaries",
            before=cleaned,
            after=boundary_repaired,
        )
        cleaned = boundary_repaired
    changes.extend(boundary_changes)

    casing_cleaned = _normalize_casing(cleaned)
    if casing_cleaned != cleaned:
        _append_change(
            changes,
            change_type="normalized_casing",
            before=cleaned,
            after=casing_cleaned,
        )
        cleaned = casing_cleaned

    compact_cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if compact_cleaned != cleaned:
        _append_change(
            changes,
            change_type="normalized_whitespace",
            before=cleaned,
            after=compact_cleaned,
        )
    cleaned = compact_cleaned

    spelling_cleaned, spelling_changes = _conservative_spelling_correction(cleaned)
    if spelling_cleaned != cleaned:
        cleaned = spelling_cleaned
    changes.extend(spelling_changes)

    flags = {
        "punctuation_only_input": bool(_PUNCT_ONLY_PATTERN.fullmatch(source_text.strip())) if source_text.strip() else False,
        "numeric_only_input": _is_numeric_only_input(source_text),
        "noise_input": _is_noise_like_input(source_text),
        "silence_like_input": bool(_EMPTY_LIKE_PATTERN.fullmatch(source_text.strip())) if source_text.strip() else False,
        "cleaned_empty": cleaned == "",
    }
    return cleaned, changes, flags


def _rule_based_clean_text(text: str) -> str:
    cleaned, _, _ = _rule_based_clean_with_changes(text)
    return cleaned
