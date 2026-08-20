"""Expand the HTR draft BEFORE correction. Ordering rule, not an optimisation.

THE RULE
--------
Correction runs only on an EXPANDED draft. Never on raw diplomatic HTR.

Why it matters, measured on 20 real raw-HTR pages corrected by
groq/openai/gpt-oss-120b in diplomatic mode:

    lines changed 255/345 (73.9%),  output 2,427 tokens/page

which is no cheaper than the whole-page rewrite the diff format replaced. And
inspecting the changes, a large share were not corrections at all but
EXPANSIONS the model performed unbidden:

    sp̃s      -> spēs         (abbreviation)
    uiuunt   -> vivunt       (u/v normalisation)
    adiuuar& -> adiuvare     (u/v + Tironian et)

That happened in a run explicitly instructed to preserve ink forms. Asking a
model not to expand does not work reliably, because expansion is the obvious
reading of a garbled abbreviated word -- the instruction fights the task.

expand-diplomatic already does this deterministically with its rules backend. So
expand first, then ask the LLM only for what rules cannot do: recognition errors.
The model stops competing with the expander, the change rate drops to real
errors, and the cost saving the diff format was supposed to deliver actually
materialises.

Ordering note: maybe_run_expand_stage() operates on a finished YAML artifact, so
it is structurally DOWNSTREAM of the LLM and cannot satisfy this rule. This module
expands the draft lines instead, upstream of prompt construction.
"""

from __future__ import annotations

from transcriber_shell.config import Settings


class ExpansionUnavailable(RuntimeError):
    """expand-diplomatic could not run, so correction must not proceed."""


def expand_draft_lines(
    lines: list[str],
    settings: Settings,
    *,
    image_filename: str = "draft.jpg",
    width: int = 2000,
    height: int = 2800,
) -> tuple[list[str], int]:
    """Expand diplomatic draft lines with the rules backend.

    Returns (expanded_lines, n_changed). Raises ExpansionUnavailable when the
    expander is missing or fails -- the caller must then skip correction rather
    than silently fall back to correcting raw text, which is the very thing the
    rule forbids.

    The rules backend is forced: this is a deterministic pre-pass, and routing it
    through an LLM backend would reintroduce the non-determinism (and the cost)
    the pre-pass exists to remove.
    """
    if not lines:
        return [], 0
    s_rules = settings.model_copy(
        update={
            "expand_diplomatic_backend": "rules",
            "expand_diplomatic_whole_document": False,
        }
    )
    try:
        from transcriber_shell.expand.bridge import expand_pagexml_lines

        _xml, expanded = expand_pagexml_lines(
            image_filename, width, height, lines, s_rules
        )
    except FileNotFoundError as exc:
        raise ExpansionUnavailable(
            f"expand-diplomatic not found ({exc}). Correction requires an expanded "
            "draft; set TRANSCRIBER_SHELL_EXPAND_DIPLOMATIC_ROOT or disable "
            "correct_mode_require_expand only for a deliberate experiment."
        ) from exc
    except Exception as exc:  # noqa: BLE001 - any expander failure blocks correction
        raise ExpansionUnavailable(
            f"expand-diplomatic failed ({type(exc).__name__}: {exc}). Refusing to "
            "correct a raw diplomatic draft."
        ) from exc

    changed = sum(1 for a, b in zip(lines, expanded) if a != b)
    return expanded, changed
