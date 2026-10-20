"""Helpers for unified-diff patches as returned by the GitHub PR files API."""

import re

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def annotate_patch(patch: str) -> tuple[str, set[int]]:
    """Prefix each patch line with its new-file line number.

    Returns the annotated text and the set of new-side line numbers that GitHub
    accepts for inline review comments (added and context lines inside hunks).
    """
    out, commentable, new_line = [], set(), None
    for raw in patch.splitlines():
        m = _HUNK.match(raw)
        if m:
            new_line = int(m.group(1))
            out.append(raw)
            continue
        if new_line is None or raw.startswith("\\"):
            out.append(raw)
        elif raw.startswith("-"):
            out.append(f"{'':>6} {raw}")
        else:
            out.append(f"{new_line:>6} {raw}")
            commentable.add(new_line)
            new_line += 1
    return "\n".join(out), commentable


def commentable_lines(patch: str | None) -> set[int]:
    return annotate_patch(patch)[1] if patch else set()
