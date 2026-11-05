"""Shape checks for eval/questions.yaml (DESIGN.md section 14). Correctness is verified by hand."""

from collections import Counter
from pathlib import Path
from typing import Any

import pytest
import yaml

QUESTIONS = Path(__file__).resolve().parents[2] / "eval" / "questions.yaml"
EXPECTED_COUNTS = {"locate": 3, "callers": 3, "layer_domain": 2, "doc_rules": 2, "check_change": 2}
FIELDS = {"id", "category", "question", "expected", "evidence", "note"}


@pytest.fixture(scope="module")
def questions() -> list[dict[str, Any]]:
    data = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    return data


def test_twelve_questions_with_unique_ids(questions: list[dict[str, Any]]) -> None:
    ids = [question["id"] for question in questions]
    assert len(ids) == 12
    assert len(set(ids)) == 12


def test_category_counts(questions: list[dict[str, Any]]) -> None:
    assert Counter(question["category"] for question in questions) == EXPECTED_COUNTS


def test_every_question_has_the_expected_fields(questions: list[dict[str, Any]]) -> None:
    for question in questions:
        assert set(question) <= FIELDS, question["id"]
        assert FIELDS - {"note"} <= set(question), question["id"]
        assert question["question"].strip(), question["id"]
        assert question["evidence"].strip(), question["id"]


def test_every_answer_is_a_non_empty_set(questions: list[dict[str, Any]]) -> None:
    for question in questions:
        expected = question["expected"]
        assert set(expected) <= {"symbols", "docs"}, question["id"]
        symbols = expected.get("symbols") or []
        docs = expected.get("docs") or []
        assert symbols or docs, question["id"]
        assert len(symbols) == len(set(symbols)), f"{question['id']}: duplicate symbols"
        assert len(docs) == len(set(docs)), f"{question['id']}: duplicate docs"
        assert all("#" in doc for doc in docs), f"{question['id']}: docs must be path#Heading"
