"""The eval runner (DESIGN.md section 14): config, prompt, the claude command per condition,
the working-directory guard and transcript names. The subprocess loop itself is covered by
the smoke run, not here."""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from grade import TRANSCRIPT_NAME
from run import (
    BASELINE_PROMPT,
    CONFIG,
    EvalConfig,
    WorkdirError,
    build_meta,
    build_prompt,
    check_workdir,
    child_env,
    command,
    decode_stderr,
    invocation,
    layout,
    load_config,
    needs_run,
    prepare_layout,
    select_questions,
    transcript_name,
)

QUESTIONS = Path(__file__).resolve().parents[2] / "eval" / "questions.yaml"
ROOT = Path("/abs/vendor/repo")
MEMEX_ROOT = Path("/abs/memex")
CONFIG_VALUES = EvalConfig(
    model="claude-test-model",
    effort="high",
    runs_per_condition=1,
    max_budget_usd=1.5,
    timeout_s=600,
    codebase="bench",
)
SHARED = [
    "claude",
    "-p",
    "--model",
    "claude-test-model",
    "--effort",
    "high",
    "--output-format",
    "stream-json",
    "--verbose",
    "--strict-mcp-config",
    "--setting-sources",
    "project,local",
    "--permission-mode",
    "dontAsk",
    "--no-session-persistence",
    "--max-budget-usd",
    "1.5",
    "--add-dir",
    str(ROOT),
]


@pytest.fixture(scope="module")
def questions() -> list[dict[str, Any]]:
    return yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))


# Config


def test_the_committed_config_pins_the_model_and_one_run() -> None:
    config = load_config(CONFIG)
    assert config.model == "claude-sonnet-5-5"
    assert config.effort == "high"
    assert config.runs_per_condition == 1
    assert config.codebase == "mealie"
    assert config.max_budget_usd > 0
    assert config.timeout_s > 0


def test_a_config_with_a_missing_key_fails(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('model = "m"\nruns_per_condition = 1\n')
    with pytest.raises(KeyError):
        load_config(path)


# Prompt


def test_the_prompt_gives_the_root_the_question_and_the_answer_format() -> None:
    prompt = build_prompt("Who calls `f`?", ROOT)
    assert str(ROOT) in prompt
    assert "Who calls `f`?" in prompt
    assert "```json" in prompt
    assert '"symbols"' in prompt
    assert '"docs"' in prompt
    assert "path#Heading" in prompt


def test_the_prompt_never_names_the_tool_under_test() -> None:
    assert "memex" not in build_prompt("q?", ROOT).lower()
    assert "memex" not in BASELINE_PROMPT.lower()


def test_the_prompt_leaks_no_expected_answer(questions: list[dict[str, Any]]) -> None:
    template = build_prompt("", ROOT)
    for question in questions:
        expected = question["expected"]
        symbols = expected.get("symbols") or []
        docs = expected.get("docs") or []
        lasts = [s.rsplit(".", 1)[-1] for s in symbols] + [d.split("#", 1)[1] for d in docs]
        for item in [*symbols, *docs, *lasts]:
            assert item.lower() not in template.lower(), item


# The claude command per condition


def test_condition_a_has_file_search_tools_and_no_mcp_server() -> None:
    argv = command("A", CONFIG_VALUES, ROOT, MEMEX_ROOT)
    assert argv == SHARED + [
        "--tools",
        "Read,Grep,Glob",
        "--allowedTools",
        "Read,Grep,Glob",
    ]
    assert "--mcp-config" not in argv


def test_condition_b_has_read_and_only_the_graph_server() -> None:
    argv = command("B", CONFIG_VALUES, ROOT, MEMEX_ROOT)
    assert argv[: len(SHARED)] == SHARED
    rest = argv[len(SHARED) :]
    assert rest[:4] == ["--tools", "Read", "--allowedTools", "Read,mcp__memex"]
    assert rest[4] == "--mcp-config"
    assert json.loads(rest[5]) == {
        "mcpServers": {
            "memex": {
                "command": "uv",
                "args": ["--directory", str(MEMEX_ROOT), "run", "memex", "serve"],
            }
        }
    }
    assert len(rest) == 6


def test_an_unknown_condition_fails() -> None:
    with pytest.raises(ValueError, match="C"):
        command("C", CONFIG_VALUES, ROOT, MEMEX_ROOT)


# Working directory guard


@pytest.mark.parametrize("name", ["CLAUDE.md", "AGENTS.md"])
def test_an_instructions_file_in_the_workdir_or_a_parent_is_refused(
    tmp_path: Path, name: str
) -> None:
    workdir = tmp_path / "a" / "work"
    workdir.mkdir(parents=True)
    (tmp_path / "a" / name).write_text("rules")
    with pytest.raises(WorkdirError, match=name):
        check_workdir(workdir)
    (tmp_path / "a" / name).unlink()
    (workdir / name).write_text("rules")
    with pytest.raises(WorkdirError, match=name):
        check_workdir(workdir)


def test_a_clean_workdir_passes(tmp_path: Path) -> None:
    workdir = tmp_path / "work"
    workdir.mkdir()
    check_workdir(workdir)


def test_a_workdir_inside_this_repo_is_refused() -> None:
    with pytest.raises(WorkdirError, match="CLAUDE.md"):
        check_workdir(Path(__file__).resolve().parent)


# Selection, names and meta


def test_select_questions_keeps_file_order_and_rejects_unknown_ids(
    questions: list[dict[str, Any]],
) -> None:
    assert [q["id"] for q in select_questions(questions, None)] == [q["id"] for q in questions]
    assert [q["id"] for q in select_questions(questions, ["q12", "q01"])] == ["q01", "q12"]
    with pytest.raises(ValueError, match="q99"):
        select_questions(questions, ["q99"])


@pytest.mark.parametrize(("qid", "condition", "run"), [("q01", "A", 1), ("baseline", "B", 1)])
def test_transcript_names_are_the_ones_the_grader_reads(qid: str, condition: str, run: int) -> None:
    name = transcript_name(qid, condition, run)
    match = TRANSCRIPT_NAME.match(name)
    assert match is not None
    assert (match["qid"], match["condition"], int(match["run"])) == (qid, condition, run)


def test_meta_has_what_the_grader_and_the_report_read() -> None:
    first = invocation(
        memex_commit="abc123",
        claude_version="9.9.9 (Claude Code)",
        argv=["--questions", "q11"],
        started="2026-11-05T12:00:00Z",
        env_removed=["CLAUDECODE"],
        jobs=["q11-B-1.jsonl"],
    )
    meta = build_meta(CONFIG_VALUES, name="smoke", root=ROOT, codebase_commit="def456")
    meta["invocations"].append(first)
    assert meta == {
        "name": "smoke",
        "root": str(ROOT),
        "codebase": "bench",
        "model": "claude-test-model",
        "effort": "high",
        "runs_per_condition": 1,
        "max_budget_usd": 1.5,
        "timeout_s": 600,
        "codebase_commit": "def456",
        "invocations": [
            {
                "memex_commit": "abc123",
                "claude_version": "9.9.9 (Claude Code)",
                "argv": ["--questions", "q11"],
                "started": "2026-11-05T12:00:00Z",
                "env_removed": ["CLAUDECODE"],
                "jobs": ["q11-B-1.jsonl"],
            }
        ],
    }


# Reviewer run 1: layout, environment, resume and stderr


def test_the_layout_keeps_the_tool_name_out_of_every_path_and_the_root_beside_the_workdir(
    tmp_path: Path,
) -> None:
    workdir, root = layout("smoke", "mealie", tmp_path)
    assert workdir == tmp_path / "eval-smoke" / "work"
    assert root == tmp_path / "eval-smoke" / "mealie"
    assert "memex" not in str(workdir).lower().replace(str(tmp_path).lower(), "")
    assert workdir not in root.parents


def test_prepare_layout_links_the_root_to_the_codebase_and_is_repeatable(tmp_path: Path) -> None:
    target = tmp_path / "vendor" / "repo"
    target.mkdir(parents=True)
    workdir, root = layout("smoke", "repo", tmp_path)
    for _ in range(2):
        prepare_layout(workdir, root, target)
        assert workdir.is_dir()
        assert root.is_symlink()
        assert root.resolve() == target.resolve()
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(WorkdirError, match="points at"):
        prepare_layout(workdir, root, other)


def test_the_real_prompt_does_not_name_the_tool_under_test(tmp_path: Path) -> None:
    _, root = layout("full", "mealie", tmp_path)
    prompt = build_prompt("Which code constructs a matcher?", root)
    assert "memex" not in prompt.lower().replace(str(tmp_path).lower(), "")


def test_child_env_drops_session_and_model_variables_and_keeps_the_rest() -> None:
    env, removed = child_env(
        {
            "PATH": "/bin",
            "HOME": "/home/u",
            "CLAUDECODE": "1",
            "CLAUDE_CODE_SESSION_ID": "s",
            "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD": "1",
            "CLAUDE_EFFORT": "low",
            "MCP_TIMEOUT": "5",
            "ANTHROPIC_MODEL": "x",
            "ANTHROPIC_DEFAULT_SONNET_MODEL": "y",
            "ANTHROPIC_SMALL_FAST_MODEL": "z",
            "ANTHROPIC_API_KEY": "k",
        }
    )
    assert env == {"PATH": "/bin", "HOME": "/home/u", "ANTHROPIC_API_KEY": "k"}
    assert removed == sorted(
        [
            "ANTHROPIC_DEFAULT_SONNET_MODEL",
            "ANTHROPIC_MODEL",
            "ANTHROPIC_SMALL_FAST_MODEL",
            "CLAUDECODE",
            "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD",
            "CLAUDE_CODE_SESSION_ID",
            "CLAUDE_EFFORT",
            "MCP_TIMEOUT",
        ]
    )


INIT = {"type": "system", "subtype": "init", "tools": ["Read"], "mcp_servers": []}
OK = {"type": "result", "subtype": "success", "is_error": False, "result": "done", "usage": {}}


@pytest.mark.parametrize(
    ("events", "expected"),
    [
        (None, True),  # no file
        ([], True),  # empty file
        ([INIT], True),  # no result
        ([INIT, {**OK, "is_error": True, "subtype": "error_max_budget_usd"}], True),
        ([INIT, OK], False),
    ],
)
def test_needs_run_skips_only_a_finished_transcript(
    tmp_path: Path, events: list[dict[str, Any]] | None, expected: bool
) -> None:
    path = tmp_path / "q01-A-1.jsonl"
    if events is not None:
        path.write_text("".join(json.dumps(event) + "\n" for event in events))
    assert needs_run(path) is expected


def test_needs_run_reruns_a_transcript_with_a_cut_off_line(tmp_path: Path) -> None:
    path = tmp_path / "q01-A-1.jsonl"
    path.write_text(json.dumps(INIT) + "\n" + json.dumps(OK) + '\n{"type": "assis')
    assert needs_run(path) is True


@pytest.mark.parametrize(
    ("value", "expected"), [(None, ""), (b"boom\n", "boom\n"), ("text", "text")]
)
def test_decode_stderr(value: bytes | str | None, expected: str) -> None:
    assert decode_stderr(value) == expected
