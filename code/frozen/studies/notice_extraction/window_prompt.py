'Insert the window clarification into the extraction prompt.'
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
INSERTIONS = (
    (
        "Every supplied evidence span, including a span attached to UNKNOWN, must occur in the title or body.",
        " Each evidence span is one contiguous exact substring of the title or of the body. Never join text from the title and the body, or from separate places, into one span. Use several spans instead.",
    ),
    (
        "Free-text values must reproduce explicit source wording, not explanations or paraphrases.",
        " Every free-text value, including each attribute value and start_text and end_text, must be copied character for character from one contiguous source passage that its evidence spans cover. Do not summarise, abbreviate, reorder, drop words, change punctuation, or join phrases with semicolons. When an attribute has several distinct source phrases, set value to the single most specific contiguous phrase and give the other phrases only as additional evidence spans.",
    ),
    (
        "- start_text.value and end_text.value preserve the exact source time wording.",
        ' start_text and end_text each copy only the exact source wording of that endpoint. Do not attach a date or time that the source states only for the other endpoint or elsewhere. For example, "From 1200 hrs to 1430 hrs 11/01/2026" gives start_text "1200 hrs" and end_text "1430 hrs 11/01/2026". Downstream code anchors dates deterministically.',
    ),
    (
        "For an unclear binding: binding_status=UNKNOWN_RELATION, window_id=null, and binding_reason=SOURCE_SCOPE_AMBIGUOUS or SOURCE_SCOPE_ABSENT.",
        " When binding_status is UNKNOWN_RELATION, window_id must be JSON null, never a window ID.",
    ),
)


def specified_prompt(base: str) -> str:
    for anchor, addition in INSERTIONS:
        if base.count(anchor) != 1 or addition in base:
            raise RuntimeError('prompt anchor is missing, duplicated or already specified')
        base = base.replace(anchor, anchor + addition, 1)
    return base


def verify_prompt(root: Path | None = None) -> dict:
    root = HERE if root is None else root
    original = (root / 'archive_label_specification/prompt.txt').read_bytes()
    expected = specified_prompt(original.decode("utf-8")).encode("utf-8")
    if (root / "prompt.txt").read_bytes() != expected:
        raise RuntimeError("v1.2 prompt must contain exactly the four frozen insertions")
    return {"state": "PASS_INSERTION_ONLY_PROMPT", "insertions": 4, "base_bytes_preserved": True}
