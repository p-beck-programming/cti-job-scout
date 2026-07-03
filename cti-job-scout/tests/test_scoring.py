"""Tests for the scoring response parser — the piece most likely to break
when the model misbehaves, so it gets the most edge cases."""

import pytest
from pydantic import ValidationError

from jobscout.scoring import parse_score_response

GOOD = '{"score": 87, "rationale": "Core CTI role.", "matched_keywords": ["CTI", "MITRE ATT&CK"]}'


def test_parses_clean_json():
    score = parse_score_response(GOOD)
    assert score.score == 87
    assert score.rationale == "Core CTI role."
    assert score.matched_keywords == ["CTI", "MITRE ATT&CK"]


def test_strips_markdown_fences():
    score = parse_score_response(f"```json\n{GOOD}\n```")
    assert score.score == 87


def test_extracts_json_from_surrounding_prose():
    score = parse_score_response(f"Here is my assessment:\n{GOOD}\nHope that helps!")
    assert score.score == 87


def test_rejects_out_of_range_score():
    with pytest.raises(ValidationError):
        parse_score_response('{"score": 150, "rationale": "x", "matched_keywords": []}')


def test_rejects_missing_rationale():
    with pytest.raises(ValidationError):
        parse_score_response('{"score": 50, "matched_keywords": []}')


def test_rejects_non_json():
    with pytest.raises(ValueError):
        parse_score_response("This posting looks like a strong match!")


def test_rejects_empty_string():
    with pytest.raises(ValueError):
        parse_score_response("")


def test_keywords_default_when_absent():
    score = parse_score_response('{"score": 10, "rationale": "Unrelated."}')
    assert score.matched_keywords == []
