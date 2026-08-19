"""Tests for diff-based HTR correction."""
from __future__ import annotations

from transcriber_shell.llm.correct_diff import (
    apply_corrections,
    build_diff_prompts,
    corrections_to_transcript,
    number_draft,
    parse_corrections,
)

DRAFT = "Sicendum quippeest\ndum frenari spiritum\nꝑmulta &iam quae\nnonapp&unt iniquitatũ"


def test_number_draft_is_one_indexed_and_drops_blanks():
    numbered, lines = number_draft("alpha\n\n  beta  \n")
    assert lines == ["alpha", "beta"]
    assert numbered == "1| alpha\n2| beta"


def test_build_diff_prompts_includes_numbered_draft():
    sys_p, user, lines = build_diff_prompts(
        draft=DRAFT, normalization_mode="diplomatic", language_hint="lat-Latn")
    assert len(lines) == 4
    assert "3| ꝑmulta &iam quae" in user
    assert "lat-Latn" in user
    assert "DIPLOMATIC MODE" in sys_p
    # The whole point: the model must be told to return only changes.
    assert "ONLY the lines you would change" in sys_p


def test_diff_prompt_is_far_smaller_than_a_rewrite_contract():
    """The saving is the output contract, so assert the instruction, not the size."""
    sys_n, _, _ = build_diff_prompts(draft=DRAFT, normalization_mode="normalized")
    assert "NORMALIZED MODE" in sys_n
    assert "corrections: []" in sys_n


def test_parse_corrections_basic():
    got = parse_corrections('corrections:\n  - line: 2\n    text: "dum frenari spiritus"\n')
    assert got == {2: "dum frenari spiritus"}


def test_parse_corrections_empty_list_means_no_changes():
    assert parse_corrections("corrections: []") == {}


def test_parse_corrections_strips_markdown_fence():
    raw = '```yaml\ncorrections:\n  - line: 1\n    text: "fixed"\n```'
    assert parse_corrections(raw) == {1: "fixed"}


def test_parse_corrections_rejects_full_protocol_yaml():
    """A model that ignores the format must fall back, not blank the page."""
    raw = "transcriptionOutput:\n  segments:\n    - text: \"whatever\"\n"
    assert parse_corrections(raw) is None


def test_parse_corrections_rejects_garbage():
    assert parse_corrections("not yaml at all: [") is None
    assert parse_corrections("") is None
    assert parse_corrections("someOtherKey: 1") is None


def test_parse_corrections_ignores_malformed_entries():
    raw = ('corrections:\n'
           '  - line: 1\n    text: "ok"\n'
           '  - line: "two"\n    text: "bad line type"\n'
           '  - line: 3\n')          # missing text
    assert parse_corrections(raw) == {1: "ok"}


def test_apply_corrections_replaces_only_listed_lines():
    lines = ["a", "b", "c"]
    merged, ignored = apply_corrections(lines, {2: "B!"})
    assert merged == ["a", "B!", "c"]
    assert ignored == []


def test_apply_corrections_reports_out_of_range():
    """A hallucinated line number means the model lost the draft -- surface it."""
    merged, ignored = apply_corrections(["a", "b"], {5: "nope", 1: "A"})
    assert merged == ["A", "b"]
    assert ignored == [5]


def test_corrections_to_transcript_shape():
    doc = corrections_to_transcript(["alpha", "", "beta"],
                                    normalization_mode="diplomatic",
                                    model_id="claude-sonnet-5")
    root = doc["transcriptionOutput"]
    assert root["metadata"]["modelId"] == "claude-sonnet-5"
    assert root["metadata"]["normalizationMode"] == "diplomatic"
    # blank lines dropped, lineRange preserved from the ORIGINAL numbering
    assert [s["text"] for s in root["segments"]] == ["alpha", "beta"]
    assert [s["lineRange"] for s in root["segments"]] == [[1, 1], [3, 3]]


def test_round_trip_preserves_unchanged_lines():
    _s, _u, lines = build_diff_prompts(draft=DRAFT, normalization_mode="diplomatic")
    corr = parse_corrections('corrections:\n  - line: 4\n    text: "non apparent iniquitatum"\n')
    merged, ignored = apply_corrections(lines, corr)
    assert not ignored
    assert merged[0] == "Sicendum quippeest"      # untouched
    assert merged[3] == "non apparent iniquitatum"  # corrected
