from transcriber_shell.stylometry.genre_signal import compute_genre_signal
from transcriber_shell.stylometry.stylo_delta import (
    burrows_delta_ranking,
    chunk_words,
    rolling_delta_classify,
)


def test_computus_calendar_signal_is_strong() -> None:
    text = """
    Aureus numerus | Littera dominicalis | Concurrentes | Septuagesima | Pascha
    1 | g | kal | Ianuarius | epacta | 18 | 7 | 10
    2 | A | non | Februarius | quadragesima | 19 | 8 | 11
    3 | b | idus | Martius | rogationes | 20 | 9 | 12
    4 | c | kal | Aprilis | pentecostes | 21 | 10 | 13
    """

    signal = compute_genre_signal(
        [text],
        "computus",
        prefer_external=False,
        granularity="page",
    )

    assert signal.top_genre == "computus_calendar"
    assert signal.top_prob > 0.90
    assert signal.confidence > 0.70
    assert any(ev["feature"] == "calendar_month_density" for ev in signal.evidence)
    assert any("pascha" in ev.get("matches", []) for ev in signal.evidence)


def test_legal_charter_formula_beats_liturgical_domini_noise() -> None:
    text = """
    Noverint universi presentes et futuri quod ego Willelmus concessi et confirmavi
    hac presenti carta totam terram meam tenendum et habendum heredibus suis in
    perpetuum. In cuius rei testimonium sigillum meum apposui. Hiis testibus
    Roberto clerico et Johanne milite. Datum anno domini millesimo ducentesimo.
    """

    signal = compute_genre_signal([text], "charter", prefer_external=False)

    assert signal.top_genre == "legal_charter"
    assert signal.genre_probs["legal_charter"] > 0.85
    assert signal.genre_probs["legal_charter"] > signal.genre_probs["liturgical"]
    assert any(ev["feature"] == "charter_formula_starters" for ev in signal.evidence)


def test_scholastic_markers_produce_theological_signal() -> None:
    text = """
    Quaestio est utrum anima sit forma corporis. Videtur quod non, quia forma
    separata non informat materiam. Sed contra est auctoritas philosophi.
    Respondeo dicendum quod anima rationalis est substantialis forma corporis,
    et per gratiam deus ordinat intellectum ad finem ultimum.
    """

    signal = compute_genre_signal([text], "quaestio", prefer_external=False)

    assert signal.top_genre == "theological_scholastic"
    assert signal.top_prob > 0.80
    assert any("respondeo" in ev.get("matches", []) for ev in signal.evidence)


def test_segment_boundaries_catch_mixed_calendar_to_charter() -> None:
    pages = [
        """
        Aureus numerus | Littera dominicalis | Concurrentes | Pascha
        1 | g | kal | Ianuarius | epacta | 18 | 7 | 10
        2 | A | non | Februarius | quadragesima | 19 | 8 | 11
        """,
        """
        Noverint universi presentes et futuri quod ego Robertus concessi hac
        presenti carta terram meam tenendum heredibus in perpetuum. Datum anno
        domini. Testibus Petro et Ricardo.
        """,
    ]

    signal = compute_genre_signal(
        pages,
        "mixed",
        prefer_external=False,
        granularity="page",
        boundary_window=1,
        boundary_min_delta=0.01,
    )

    assert [seg["best_genre"] for seg in signal.segment_scores] == [
        "computus_calendar",
        "legal_charter",
    ]
    assert signal.boundary_indices == [1]


def test_round_trip_dict_keeps_new_evidence_fields() -> None:
    signal = compute_genre_signal(["Recipe herbam et aquam; misce contra febrem."], "rx", prefer_external=False)
    restored = type(signal).from_dict(signal.to_dict())

    assert restored.top_genre == "medical_recipe"
    assert restored.evidence
    assert restored.confidence == signal.confidence


def test_stylometry_r_delta_port_classifies_against_references() -> None:
    refs = {
        "calendar": [
            "kal non idus ianuarius februarius martius pascha epacta aureus numerus",
            "kalendas nonas idus aprilis maius iunius dominicalis concurrentes",
        ],
        "charter": [
            "noverint universi presentes futuri concessi carta sigillum testibus",
            "datum anno domini tenendum habendum heredibus imperpetuum confirmavi",
        ],
    }
    features = (
        "kal",
        "non",
        "idus",
        "ianuarius",
        "pascha",
        "epacta",
        "noverint",
        "carta",
        "sigillum",
        "testibus",
        "datum",
    )

    ranking = burrows_delta_ranking(
        refs,
        "aureus numerus kal ianuarius epacta pascha non idus",
        features,
    )

    assert ranking[0].label == "calendar"
    assert ranking[0].distance < ranking[1].distance

    chunks = chunk_words(" ".join(str(i) for i in range(4500)), chunk_words=2000)
    assert len(chunks) == 2

    rolling = rolling_delta_classify(
        refs,
        "kal non idus pascha epacta " * 80,
        features,
        slice_words=120,
        overlap=60,
    )
    assert rolling.counts["calendar"] == len(rolling.predictions)
