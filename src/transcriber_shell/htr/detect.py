"""Language/script detection for HTR model routing.

Heuristics based on prompt config keywords. Returns a set of script tags
("latin", "latin-french", "english-medieval") used by the parallel runner
to select which HTR backends to invoke.
"""

from __future__ import annotations

import re

_LATIN_FRENCH_KEYWORDS = frozenset({
    "latin", "french", "français", "medieval latin", "mediaeval", "notarial",
    "charter", "papal", "ecclesiastical", "deed", "parchment",
})

_ENGLISH_MEDIEVAL_KEYWORDS = frozenset({
    "english", "middle english", "anglo", "chancery", "court roll", "manorial",
    "inquisition", "patent", "close roll",
})


def detect_scripts(prompt_cfg: dict | None, *, default: str = "latin-french") -> set[str]:
    """Return script tags inferred from prompt_cfg text fields.

    Falls back to ``default`` when the config contains no recognisable keywords.
    """
    if not prompt_cfg:
        return {default}

    haystack = " ".join(
        str(v).lower()
        for k, v in prompt_cfg.items()
        if isinstance(v, str)
    )

    detected: set[str] = set()

    for kw in _LATIN_FRENCH_KEYWORDS:
        if re.search(r"\b" + re.escape(kw) + r"\b", haystack):
            detected.add("latin-french")
            break

    for kw in _ENGLISH_MEDIEVAL_KEYWORDS:
        if re.search(r"\b" + re.escape(kw) + r"\b", haystack):
            detected.add("english-medieval")
            break

    return detected or {default}
