"""Tests for transcription YAML enum normalization before protocol validation."""

from __future__ import annotations

from transcriber_shell.llm.validate_output import (
    _normalize_position_value,
    normalize_transcription_yaml_data,
)


def test_normalize_position_case_and_hyphens() -> None:
    assert _normalize_position_value("Body") == "body"
    assert _normalize_position_value("MARGIN_LEFT") == "margin_left"
    assert _normalize_position_value("margin-left") == "margin_left"
    assert _normalize_position_value(" margin right ") == "margin_right"


def test_normalize_position_synonyms() -> None:
    assert _normalize_position_value("main") == "body"
    assert _normalize_position_value("Main") == "body"


def test_normalize_marginalia_aliases() -> None:
    assert _normalize_position_value("marginalia_left") == "margin_left"
    assert _normalize_position_value("Marginalia_Right") == "margin_right"
    assert _normalize_position_value("margin") == "margin_left"


def test_normalize_title_and_attestation_aliases() -> None:
    assert _normalize_position_value("title") == "header"
    assert _normalize_position_value("attestation_block") == "footer"
    assert _normalize_position_value("Attestation_Block") == "footer"


def test_normalize_transcription_yaml_data_mutates_segments() -> None:
    data = {
        "transcriptionOutput": {
            "metadata": {"runMode": " Standard "},
            "segments": [
                {
                    "segmentId": 0,
                    "pageNumber": 1,
                    "lineRange": "1",
                    "position": "Body",
                    "text": "a",
                    "confidence": "High",
                    "uncertaintyTokenCount": 0,
                    "notes": None,
                }
            ],
        }
    }
    normalize_transcription_yaml_data(data)
    seg = data["transcriptionOutput"]["segments"][0]
    assert seg["position"] == "body"
    assert seg["confidence"] == "high"
    assert data["transcriptionOutput"]["metadata"]["runMode"] == "standard"
    assert data["transcriptionOutput"]["protocolVersion"] == "1.1.0"
    assert data["transcriptionOutput"]["metadata"]["protocolVersion"] == "1.1.0"


def test_normalize_protocol_and_modality_fixes() -> None:
    data = {
        "transcriptionOutput": {
            "metadata": {
                "targetLanguage": "lat-med",
                "englishHandwritingModality": "cursive",
            },
            "segments": [],
        }
    }
    normalize_transcription_yaml_data(data)
    root = data["transcriptionOutput"]
    assert root["protocolVersion"] == "1.1.0"
    assert root["metadata"]["protocolVersion"] == "1.1.0"
    assert root["metadata"]["englishHandwritingModality"] is None
