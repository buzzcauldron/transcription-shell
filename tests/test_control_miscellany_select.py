from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "control_miscellany" / "select_cohort.py"
SPEC = importlib.util.spec_from_file_location("select_cohort", SCRIPT)
assert SPEC and SPEC.loader
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def test_parse_search_ids_from_dropdown() -> None:
    html = """
    <option value="https://www.e-codices.unifr.ch/en/searchresult/list/one/csg/0150">
    <option value="https://www.e-codices.unifr.ch/en/searchresult/list/one/ubb/A-IV-0006">
    """
    assert M.parse_search_ids(html) == [("csg", "0150"), ("ubb", "A-IV-0006")]


def test_search_page_count() -> None:
    html = "<strong>437</strong> \n        documents found"
    assert M.search_page_count(html) == 437


def test_classify_accepts_latin_composite_penitential() -> None:
    meta = {
        "Title (English)": "Composite manuscript containing books of pennance",
        "Summary (English)": "This five-part composite manuscript contains penitentials and Church Fathers.",
        "Text Language": "Latin",
        "Century": "9th century",
        "Document Type": "Manuscript",
        "Number of Pages": "414",
    }
    v = M.classify_record(meta, meta["Summary (English)"])
    assert v["ok"] is True
    assert v["mixed"] is True


def test_classify_rejects_computus_composite() -> None:
    meta = {
        "Title (English)": "Composite manuscript",
        "Summary (English)": "A composite manuscript containing various texts related to figuring Easter dates.",
        "Text Language": "Latin",
        "Century": "10th century",
        "Document Type": "Manuscript",
        "Number of Pages": "80",
    }
    v = M.classify_record(meta, meta["Summary (English)"])
    assert v["ok"] is False
    assert "computus_content" in v["reasons"]


def test_classify_rejects_german_only_and_psalter() -> None:
    german = M.classify_record(
        {
            "Title (English)": "Composite manuscript of mystical texts",
            "Summary (English)": "A composite manuscript in Alemannic.",
            "Text Language": "German",
            "Century": "15th century",
            "Document Type": "Manuscript",
            "Number of Pages": "200",
        },
        "",
    )
    assert german["ok"] is False
    psalter = M.classify_record(
        {
            "Title (English)": "Psalter",
            "Summary (English)": "Gallican psalter in a composite binding.",
            "Text Language": "Latin",
            "Century": "9th century",
            "Document Type": "Manuscript",
            "Number of Pages": "300",
        },
        "",
    )
    assert psalter["ok"] is False
    assert "single_liturgical" in psalter["reasons"]
    breviary = M.classify_record(
        {
            "Title (English)": "Breviary from the monastery of Disentis",
            "Summary (English)": "A liturgical breviary.",
            "Text Language": "Latin",
            "Century": "12th century",
            "Document Type": "Manuscript",
            "Number of Pages": "638",
        },
        "",
    )
    assert breviary["ok"] is False
    assert "single_liturgical" in breviary["reasons"]


def test_slug_and_registry_exclusion() -> None:
    assert M.slug_for("csg", "0150") == "ctrl_csg_0150"
    ids = M.computus_ecodices_ids(Path("/no/such/registry.jsonl"))
    assert ids == set()
