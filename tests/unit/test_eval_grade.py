"""The eval grader (DESIGN.md section 14): answer blocks, normalization, set scores,
transcripts and the per-condition summary. Deterministic, no LLM."""

import json
from pathlib import Path
from typing import Any

import pytest
from grade import (
    Answer,
    Score,
    Usage,
    extract_answer,
    grade_question,
    main,
    normalize_doc,
    normalize_symbol,
    read_transcript,
    score,
    summarize,
)

ROOT = "/abs/path/to/repo"

QUESTION: dict[str, Any] = {
    "id": "q90",
    "category": "callers",
    "question": "Who calls things?",
    "expected": {
        "symbols": ["pkg.a.Alpha", "pkg.b.beta", "pkg.c.Gamma.run"],
        "docs": ["GUIDE.md#Rules"],
    },
}


def fenced(body: str, lang: str = "json") -> str:
    return f"```{lang}\n{body}\n```"


# Answer blocks


def test_the_last_json_block_is_the_answer() -> None:
    text = "\n".join(
        [
            "First draft:",
            fenced('{"symbols": ["x.old"], "docs": []}'),
            "Final:",
            fenced('{"symbols": ["x.new"], "docs": ["A.md#H"]}'),
        ]
    )
    assert extract_answer(text) == Answer(symbols=("x.new",), docs=("A.md#H",))


def test_a_missing_key_is_an_empty_list() -> None:
    assert extract_answer(fenced('{"symbols": ["x.y"]}')) == Answer(symbols=("x.y",), docs=())


@pytest.mark.parametrize(
    "text",
    [
        "No block at all.",
        fenced('{"symbols": ["x.y"], "docs": []'),  # invalid JSON
        fenced('["x.y"]'),  # not an object
        fenced('{"symbols": "x.y", "docs": []}'),  # not a list
        fenced('{"symbols": [1], "docs": []}'),  # not strings
        fenced('{"symbols": ["x.y"], "docs": []}', lang="python"),  # not a json fence
    ],
)
def test_no_valid_block_gives_none(text: str) -> None:
    assert extract_answer(text) is None


# Normalization


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("pkg.a.Alpha", "pkg.a.alpha"),
        ("  `pkg.a.Alpha`  ", "pkg.a.alpha"),
        ("pkg.b.beta()", "pkg.b.beta"),
        ("`pkg.b.beta()`", "pkg.b.beta"),
    ],
)
def test_normalize_symbol(raw: str, expected: str) -> None:
    assert normalize_symbol(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("GUIDE.md#Rules", "guide.md#rules"),
        ("`GUIDE.md#Rules`", "guide.md#rules"),
        ("GUIDE.md#  Common   Rules ", "guide.md#common rules"),
        ("GUIDE.md#Architecture > Backend > Rules", "guide.md#rules"),
        ("./docs/x.md#Overview", "docs/x.md#overview"),
        (f"{ROOT}/docs/x.md#Overview", "docs/x.md#overview"),
        (f"{ROOT}/GUIDE.md#Rules", "guide.md#rules"),
        ("GUIDE.md", "guide.md"),
    ],
)
def test_normalize_doc(raw: str, expected: str) -> None:
    assert normalize_doc(raw, ROOT) == expected


# Set scores


def test_score_counts_precision_recall_and_f1() -> None:
    result = score(expected={"a", "b", "c", "d"}, got={"a", "b", "x"})
    assert result == Score(precision=2 / 3, recall=0.5, f1=pytest.approx(4 / 7))


def test_score_with_empty_sets() -> None:
    assert score(expected=set(), got=set()) == Score(precision=1.0, recall=1.0, f1=1.0)
    assert score(expected=set(), got={"x"}) == Score(precision=0.0, recall=1.0, f1=0.0)
    assert score(expected={"a"}, got=set()) == Score(precision=0.0, recall=0.0, f1=0.0)


# One question


def test_grade_question_scores_symbols_docs_and_the_combined_set() -> None:
    answer = "\n".join(
        [
            "Here is what I found.",
            fenced(
                json.dumps(
                    {
                        "symbols": ["`pkg.a.Alpha`", "pkg.b.beta()", "pkg.z.Extra"],
                        "docs": [f"{ROOT}/GUIDE.md#Top > Rules"],
                    }
                )
            ),
        ]
    )
    grade = grade_question(QUESTION, answer, ROOT)
    assert grade.answered is True
    assert grade.symbols == Score(precision=2 / 3, recall=2 / 3, f1=pytest.approx(2 / 3))
    assert grade.docs == Score(precision=1.0, recall=1.0, f1=1.0)
    assert grade.combined == Score(precision=0.75, recall=0.75, f1=0.75)
    assert grade.missed == ("pkg.c.Gamma.run",)
    assert grade.extra == ("pkg.z.Extra",)


def test_a_question_with_no_expected_docs_is_not_penalized_for_none() -> None:
    question = {**QUESTION, "expected": {"symbols": ["pkg.a.Alpha"], "docs": []}}
    grade = grade_question(question, fenced('{"symbols": ["pkg.a.Alpha"], "docs": []}'), ROOT)
    assert grade.docs == Score(precision=1.0, recall=1.0, f1=1.0)
    assert grade.combined == Score(precision=1.0, recall=1.0, f1=1.0)


def test_a_question_with_no_expected_symbols_reads_a_null_list_as_empty() -> None:
    question = {**QUESTION, "expected": {"symbols": None, "docs": ["GUIDE.md#Rules"]}}
    grade = grade_question(question, fenced('{"symbols": [], "docs": ["GUIDE.md#Rules"]}'), ROOT)
    assert grade.symbols == Score(precision=1.0, recall=1.0, f1=1.0)
    assert grade.combined == Score(precision=1.0, recall=1.0, f1=1.0)


def test_an_unanswered_question_scores_zero_and_misses_everything() -> None:
    grade = grade_question(QUESTION, "I could not find it.", ROOT)
    assert grade.answered is False
    assert grade.combined == Score(precision=0.0, recall=0.0, f1=0.0)
    assert grade.missed == ("GUIDE.md#Rules", "pkg.a.Alpha", "pkg.b.beta", "pkg.c.Gamma.run")
    assert grade.extra == ()


def test_missed_and_extra_keep_the_original_spelling_once_each() -> None:
    answer = fenced('{"symbols": ["pkg.a.Alpha", "`PKG.A.ALPHA`", "pkg.q.New", "pkg.q.new()"]}')
    grade = grade_question(QUESTION, answer, ROOT)
    assert grade.extra == ("pkg.q.New",)
    assert grade.symbols.precision == 0.5


# Transcripts (stream-json lines)

INIT = {
    "type": "system",
    "subtype": "init",
    "model": "claude-sonnet-5-5",
    "tools": ["Read", "mcp__memex__find_symbol"],
    "mcp_servers": [{"name": "memex", "status": "connected"}],
}
ASSISTANT_TOOLS = {
    "type": "assistant",
    "message": {
        "content": [
            {"type": "text", "text": "Looking."},
            {"type": "tool_use", "id": "t1", "name": "mcp__memex__find_symbol", "input": {}},
            {"type": "tool_use", "id": "t2", "name": "Read", "input": {}},
        ]
    },
}
TOOL_RESULT = {"type": "user", "message": {"content": [{"type": "tool_result"}]}}
ASSISTANT_READ = {
    "type": "assistant",
    "message": {"content": [{"type": "tool_use", "id": "t3", "name": "Read", "input": {}}]},
}
RESULT = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "result": fenced('{"symbols": ["pkg.a.Alpha"], "docs": []}'),
    "num_turns": 4,
    "duration_ms": 12_500,
    "total_cost_usd": 0.042,
    "usage": {
        "input_tokens": 120,
        "output_tokens": 800,
        "cache_creation_input_tokens": 9_000,
        "cache_read_input_tokens": 30_000,
    },
}


def lines(*events: dict[str, Any]) -> list[str]:
    return [json.dumps(event) for event in events] + [""]


def test_read_transcript_takes_init_tool_calls_and_the_result() -> None:
    transcript = read_transcript(lines(INIT, ASSISTANT_TOOLS, TOOL_RESULT, ASSISTANT_READ, RESULT))
    assert transcript.tools == ("Read", "mcp__memex__find_symbol")
    assert transcript.mcp_servers == (("memex", "connected"),)
    assert transcript.tool_calls == ("mcp__memex__find_symbol", "Read", "Read")
    assert transcript.result_text == RESULT["result"]
    assert transcript.is_error is False
    assert transcript.usage == Usage(
        input_tokens=120,
        output_tokens=800,
        cache_creation_tokens=9_000,
        cache_read_tokens=30_000,
        cost_usd=0.042,
        turns=4,
        duration_ms=12_500,
    )


def test_a_transcript_without_a_result_is_an_error_with_zero_usage() -> None:
    transcript = read_transcript(lines(INIT, ASSISTANT_TOOLS))
    assert transcript.is_error is True
    assert transcript.result_text == ""
    assert transcript.usage == Usage()
    assert transcript.tool_calls == ("mcp__memex__find_symbol", "Read")


def test_an_error_result_is_an_error() -> None:
    error = {**RESULT, "subtype": "error_max_budget_usd", "is_error": True, "result": ""}
    assert read_transcript(lines(INIT, error)).is_error is True


def test_usage_total_input_counts_cache_too() -> None:
    usage = Usage(input_tokens=1, output_tokens=2, cache_creation_tokens=3, cache_read_tokens=4)
    assert usage.total_input == 8


# Summary per condition


def run_row(qid: str, category: str, condition: str, f1_symbols: list[str]) -> dict[str, Any]:
    question = {**QUESTION, "id": qid, "category": category}
    text = fenced(json.dumps({"symbols": f1_symbols, "docs": ["GUIDE.md#Rules"]}))
    transcript = read_transcript(lines(INIT, {**RESULT, "result": text}))
    return {
        "question": question,
        "condition": condition,
        "run": 1,
        "grade": grade_question(question, text, ROOT),
        "transcript": transcript,
    }


def test_summarize_averages_by_condition_and_category_and_sums_usage() -> None:
    full = ["pkg.a.Alpha", "pkg.b.beta", "pkg.c.Gamma.run"]
    rows = [
        run_row("q90", "callers", "A", full),  # f1 1.0
        run_row("q91", "locate", "A", []),  # docs only: p 1, r 0.25
        run_row("q90", "callers", "B", full),
        run_row("q91", "locate", "B", full),
    ]
    summary = summarize(rows)
    assert set(summary) == {"A", "B"}
    a = summary["A"]
    assert a["runs"] == 2
    assert a["answered"] == 2
    assert a["errors"] == 0
    assert a["precision"] == pytest.approx(1.0)
    assert a["recall"] == pytest.approx((1.0 + 0.25) / 2)
    assert a["f1"] == pytest.approx((1.0 + 0.4) / 2)
    assert a["by_category"] == {
        "callers": pytest.approx(1.0),
        "locate": pytest.approx(0.4),
    }
    assert a["usage"] == {
        "input_tokens": 240,
        "output_tokens": 1_600,
        "cache_creation_tokens": 18_000,
        "cache_read_tokens": 60_000,
        "total_input": 78_240,
        "cost_usd": pytest.approx(0.084),
        "turns": 8,
        "duration_ms": 25_000,
    }
    assert summary["B"]["f1"] == pytest.approx(1.0)


# A run folder


def test_grade_run_writes_the_same_scores_twice_and_reports_each_question(tmp_path: Path) -> None:
    question = {**QUESTION, "id": "q01"}
    (tmp_path / "meta.json").write_text(json.dumps({"name": "t", "root": ROOT}))
    answer = fenced('{"symbols": ["pkg.a.Alpha"], "docs": []}')
    (tmp_path / "q01-B-1.jsonl").write_text("\n".join(lines(INIT, {**RESULT, "result": answer})))
    (tmp_path / "baseline-B-1.jsonl").write_text("\n".join(lines(INIT, RESULT)))
    (tmp_path / "notes.jsonl").write_text("ignored")
    questions_file = tmp_path / "questions.yaml"
    questions_file.write_text(json.dumps([question]))  # JSON is valid YAML

    assert main([str(tmp_path), "--questions", str(questions_file)]) == 0
    first = (tmp_path / "scores.json").read_text()
    assert main([str(tmp_path), "--questions", str(questions_file)]) == 0
    assert (tmp_path / "scores.json").read_text() == first

    scores = json.loads(first)
    assert [run["id"] for run in scores["runs"]] == ["q01"]
    assert scores["runs"][0]["combined"]["recall"] == 0.25
    assert scores["runs"][0]["tool_calls"] == {}
    assert scores["baselines"]["B"]["mcp_servers"] == [["memex", "connected"]]
    report = (tmp_path / "results.md").read_text()
    assert "| q01 | callers | B | 0.40 |" in report
    assert "- missed: `pkg.b.beta`" in report
