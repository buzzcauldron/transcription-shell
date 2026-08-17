from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path("/Users/halxiii/Projects/stylometry-r/scripts/cluster_computus_types.py")
SPEC = importlib.util.spec_from_file_location("cluster_computus_types", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_normalise_maps_ae_and_v() -> None:
    assert MODULE.normalise_latin("Paschæ") == "pasche"
    assert "computus" in MODULE.normalise_latin("Computus").split()
    assert "kalendas" in MODULE.normalise_latin("Kalendas").split()


def test_computus_score_needs_several_stems() -> None:
    words = MODULE.normalise_latin(
        "De epactis lunaribus epacta ad cursum solarem pascha die dominico kalendas"
    ).split()
    score, hits = MODULE.computus_score(words)
    assert score >= 3
    assert "epact" in hits
    assert "pasch" in hits


def test_grammar_chunk_is_not_computus() -> None:
    words = MODULE.normalise_latin(
        "Nominatiuo magister genitiuo magistri datiuo magistro accusatiuo magistrum"
    ).split()
    score, _ = MODULE.computus_score(words)
    assert score < MODULE.SEED_MIN_SCORE


def test_modern_title_card_is_dropped() -> None:
    words = MODULE.normalise_latin(
        "COMPUTUS chirometralis WELLCOME HISTORICAL MEDICAL LIBRARY contents the and"
    ).split()
    assert MODULE.is_modern_paratext(words)


def test_counterpoint_role() -> None:
    assert MODULE.is_counterpoint("astronomical teaching counterpoint")
    assert not MODULE.is_counterpoint("Carolingian computus collection")


def test_context_is_host_not_computus_type() -> None:
    assert MODULE.context_for("sb_878_cod", "direct_computus") == "carolingian_school"
    assert MODULE.hero_context_for("sb_878_cod") == "vademecum"
    assert MODULE.context_for("bnf_lat_4860_cod", "") == "anthology"
    assert MODULE.hero_context_for("bnf_lat_4860_cod") == "florilegium"
    assert MODULE.context_for("oxford_sjc_17", "") == "diagrammatic_album"
    assert MODULE.context_for("sb_732_cod", "") == "puncture_host"
    assert MODULE.context_for("x", "scholastic natural-philosophy counterpoint") == "counterpoint"


def test_same_type_can_sit_in_two_contexts() -> None:
    chunks = [
        {"topic_primary": 3, "family": "chronology", "context": "carolingian_school"},
        {"topic_primary": 3, "family": "chronology", "context": "diagrammatic_album"},
        {"topic_primary": 1, "family": "paschal", "context": "anthology"},
    ]
    rows = {r["family"]: r for r in MODULE.type_context_counts(chunks)}
    assert rows["chronology"]["carolingian_school"] == 1
    assert rows["chronology"]["diagrammatic_album"] == 1
    assert rows["paschal"]["anthology"] == 1
    assert rows["chronology"]["n"] == 2


def test_family_from_top_words_paschal() -> None:
    assert MODULE.family_from_top_words("pascha pasche xiiii lune") == "paschal"
    assert MODULE.family_from_top_words("hora horas circulus sol") == "hours_circulus"
    import numpy as np

    p = np.array([0.5, 0.3, 0.2])
    assert MODULE.jsd(p, p) < 1e-9


def test_bipartite_edges_are_cells_not_clusters() -> None:
    chunks = [
        {"topic_primary": 3, "family": "chronology", "context": "carolingian_school"},
        {"topic_primary": 3, "family": "chronology", "context": "diagrammatic_album"},
    ]
    edges = {(e["type"], e["context"]): e["chunks"] for e in MODULE.bipartite_edges(MODULE.type_context_counts(chunks))}
    assert edges[("chronology", "carolingian_school")] == 1
    assert edges[("chronology", "diagrammatic_album")] == 1
