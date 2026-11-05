"""Run the eval questions through headless Claude Code (DESIGN.md section 14).

Usage:
  uv run python eval/run.py --name <run> [--questions q11 ...] [--conditions A B]
                            [--baseline] [--no-questions] [--overwrite]

Condition A gets Read, Grep and Glob; condition B gets Read and the Memex MCP tools. Same
model, effort, prompt and working directory. The layout, under the system temp dir:

  eval-<run>/work      the working directory: empty, outside this repo, so no CLAUDE.md or
                       AGENTS.md is loaded
  eval-<run>/<name>    a symlink to the codebase, added through --add-dir; it sits beside the
                       workdir, not inside it, and keeps this tool's name out of the prompt

Each call runs with the Claude Code session variables of the calling shell removed and is
saved verbatim as eval/results/<run>/<qid>-<condition>-<n>.jsonl (stream-json). A finished
transcript is skipped on the next invocation; an unfinished one is run again. Grade with
eval/grade.py.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from grade import check_tools, read_transcript

import memex.config

EVAL = Path(__file__).resolve().parent
REPO = EVAL.parent
CONFIG = EVAL / "config.toml"
QUESTIONS = EVAL / "questions.yaml"
RESULTS = EVAL / "results"
CONDITIONS = ("A", "B")
INSTRUCTION_FILES = ("CLAUDE.md", "AGENTS.md")
# Variables a child claude must not inherit: the calling session's own (CLAUDECODE, session
# ids, messaging socket, effort, extra CLAUDE.md dirs), MCP tuning and model overrides.
ENV_PREFIXES = (
    "CLAUDE",
    "MCP_",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_",
    "ANTHROPIC_SMALL_FAST_MODEL",
)

PROMPT = """\
You are answering a question about the Python codebase at {root}.

Question: {question}

Answer in prose, then end your reply with exactly one fenced json block that lists every item \
your answer names, in this shape:

```json
{{"symbols": ["pkg.module.ClassName.method_name", "pkg.module.function_name"], \
"docs": ["docs/guide.md#Section Heading"]}}
```

- "symbols": full dotted qualified names: the module's dotted path from the codebase root, \
then the class, then the method. For a whole module, give the module's dotted path.
- "docs": documentation sections as path#Heading, with the file path relative to {root} and \
the section heading's plain text (no leading # and no Markdown formatting).
- Use an empty list when there is nothing of that kind. List only items that belong in the \
answer.
"""
BASELINE_PROMPT = "Reply with the single word OK."


class WorkdirError(Exception):
    """The working directory would load project instructions into the eval."""


@dataclass(frozen=True)
class EvalConfig:
    model: str
    effort: str
    runs_per_condition: int
    max_budget_usd: float
    timeout_s: int
    codebase: str


def load_config(path: Path) -> EvalConfig:
    """Read eval/config.toml; every key is required."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return EvalConfig(
        model=str(data["model"]),
        effort=str(data["effort"]),
        runs_per_condition=int(data["runs_per_condition"]),
        max_budget_usd=float(data["max_budget_usd"]),
        timeout_s=int(data["timeout_s"]),
        codebase=str(data["codebase"]),
    )


def build_prompt(question: str, root: Path) -> str:
    """The prompt for one question; the same text in every condition."""
    return PROMPT.format(root=root, question=question)


def command(condition: str, config: EvalConfig, root: Path, memex_root: Path) -> list[str]:
    """The claude argv for one condition. The prompt goes on stdin."""
    shared = [
        "claude",
        "-p",
        "--model",
        config.model,
        "--effort",
        config.effort,
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
        str(config.max_budget_usd),
        "--add-dir",
        str(root),
    ]
    if condition == "A":
        return shared + ["--tools", "Read,Grep,Glob", "--allowedTools", "Read,Grep,Glob"]
    if condition == "B":
        server = {
            "command": "uv",
            "args": ["--directory", str(memex_root), "run", "memex", "serve"],
        }
        return shared + [
            "--tools",
            "Read",
            "--allowedTools",
            "Read,mcp__memex",
            "--mcp-config",
            json.dumps({"mcpServers": {"memex": server}}),
        ]
    raise ValueError(f"unknown condition {condition!r}; expected one of {', '.join(CONDITIONS)}")


def check_workdir(workdir: Path) -> None:
    """Refuse a working directory that would auto-load a CLAUDE.md or AGENTS.md."""
    for folder in [workdir.resolve(), *workdir.resolve().parents]:
        for name in INSTRUCTION_FILES:
            if (folder / name).exists():
                raise WorkdirError(f"{folder / name} would be loaded into every eval call")


def select_questions(
    questions: list[dict[str, Any]], ids: Sequence[str] | None
) -> list[dict[str, Any]]:
    """The questions with these ids, in file order; all of them when ids is None."""
    if ids is None:
        return list(questions)
    unknown = sorted(set(ids) - {question["id"] for question in questions})
    if unknown:
        raise ValueError(f"unknown question ids: {', '.join(unknown)}")
    return [question for question in questions if question["id"] in set(ids)]


def transcript_name(qid: str, condition: str, run: int) -> str:
    return f"{qid}-{condition}-{run}.jsonl"


def build_meta(
    config: EvalConfig, *, name: str, root: Path, codebase_commit: str
) -> dict[str, Any]:
    """What a run folder holds; each eval/run.py invocation is appended to `invocations`."""
    return {
        "name": name,
        "root": str(root),
        "codebase": config.codebase,
        "model": config.model,
        "effort": config.effort,
        "runs_per_condition": config.runs_per_condition,
        "max_budget_usd": config.max_budget_usd,
        "timeout_s": config.timeout_s,
        "codebase_commit": codebase_commit,
        "invocations": [],
    }


def invocation(
    *,
    memex_commit: str,
    claude_version: str,
    argv: Sequence[str],
    started: str,
    env_removed: Sequence[str],
    jobs: Sequence[str],
) -> dict[str, Any]:
    return {
        "memex_commit": memex_commit,
        "claude_version": claude_version,
        "argv": list(argv),
        "started": started,
        "env_removed": list(env_removed),
        "jobs": list(jobs),
    }


def layout(name: str, codebase: str, tmp: Path) -> tuple[Path, Path]:
    """The working directory and the codebase link for a run, side by side."""
    base = tmp / f"eval-{name}"
    return base / "work", base / codebase


def prepare_layout(workdir: Path, root: Path, target: Path) -> None:
    """Create the workdir and link root to target; refuse a root that is something else."""
    workdir.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        if root.resolve() != target.resolve():
            raise WorkdirError(f"{root} points at {root.resolve()}, not {target}")
    elif root.exists():
        raise WorkdirError(f"{root} exists and is not a link")
    else:
        root.symlink_to(target.resolve(), target_is_directory=True)
    check_workdir(workdir)


def child_env(environ: Mapping[str, str]) -> tuple[dict[str, str], list[str]]:
    """The environment for a child claude, and the sorted names removed from it."""
    removed = sorted(key for key in environ if key.startswith(ENV_PREFIXES))
    return {k: v for k, v in environ.items() if k not in removed}, removed


def needs_run(path: Path) -> bool:
    """False only for a transcript that ended in a result without an error or a bad line."""
    if not path.exists():
        return True
    transcript = read_transcript(path.read_text(encoding="utf-8").splitlines())
    return transcript.is_error or transcript.bad_lines > 0


def decode_stderr(value: bytes | str | None) -> str:
    """TimeoutExpired.stderr can be bytes or None even with text=True."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


# The loop: thin glue, exercised by the smoke run


def _git_commit(folder: Path) -> str:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=folder, capture_output=True, text=True, check=True
        ).stdout.strip()

    commit = git("rev-parse", "HEAD")
    return commit + ("-dirty" if git("status", "--porcelain", "--untracked-files=no") else "")


def _call(
    argv: list[str], prompt: str, out: Path, workdir: Path, timeout_s: int, env: dict[str, str]
) -> None:
    """One claude call; stdout goes straight to the transcript, so a timeout keeps it."""
    stderr_path = out.with_suffix(".stderr")
    stderr_path.unlink(missing_ok=True)
    with out.open("w", encoding="utf-8") as stream:
        try:
            done = subprocess.run(
                argv,
                input=prompt,
                stdout=stream,
                stderr=subprocess.PIPE,
                cwd=workdir,
                env=env,
                text=True,
                timeout=timeout_s,
            )
            stderr = done.stderr
        except subprocess.TimeoutExpired as expired:
            stderr = f"timeout after {timeout_s} s\n{decode_stderr(expired.stderr)}"
    if stderr and stderr.strip():
        stderr_path.write_text(stderr, encoding="utf-8")


def _status(out: Path, condition: str) -> str:
    transcript = read_transcript(out.read_text(encoding="utf-8").splitlines())
    usage = transcript.usage
    problem = check_tools(condition, transcript)
    state = f"INVALID ({problem})" if problem else ("ERROR" if transcript.is_error else "ok")
    return (
        f"{state}: {usage.total_input:,} input, {usage.output_tokens:,} output, "
        f"{usage.turns} turns, {len(transcript.tool_calls)} tool calls, ${usage.cost_usd:.3f}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", required=True, help="run folder name under eval/results/")
    parser.add_argument("--questions", nargs="+", help="question ids (default: all)")
    parser.add_argument("--conditions", nargs="+", choices=CONDITIONS, default=list(CONDITIONS))
    parser.add_argument("--baseline", action="store_true", help="also run the baseline prompt")
    parser.add_argument("--no-questions", action="store_true", help="skip the questions")
    parser.add_argument("--overwrite", action="store_true", help="re-run finished transcripts")
    args = parser.parse_args(argv)

    config = load_config(CONFIG)
    codebase = memex.config.load_config(REPO / "memex.toml").get(config.codebase)
    questions = select_questions(
        yaml.safe_load(QUESTIONS.read_text(encoding="utf-8")), args.questions
    )
    workdir, root = layout(args.name, config.codebase, Path(tempfile.gettempdir()).resolve())
    prepare_layout(workdir, root, codebase.root)
    env, removed = child_env(os.environ)

    folder = RESULTS / args.name
    folder.mkdir(parents=True, exist_ok=True)
    meta_path = folder / "meta.json"
    fresh = build_meta(
        config, name=args.name, root=root, codebase_commit=_git_commit(codebase.root)
    )
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        fixed = ("root", "model", "effort", "runs_per_condition", "codebase_commit")
        changed = [key for key in fixed if meta.get(key) != fresh[key]]
        if changed:
            print(f"error: {folder} was run with other {', '.join(changed)}", file=sys.stderr)
            return 1
    else:
        meta = fresh

    jobs: list[tuple[str, str, int, str]] = []
    if args.baseline:
        jobs += [("baseline", condition, 1, BASELINE_PROMPT) for condition in args.conditions]
    if not args.no_questions:
        for question in questions:
            prompt = build_prompt(question["question"], root)
            for condition in args.conditions:
                for run in range(1, config.runs_per_condition + 1):
                    jobs.append((question["id"], condition, run, prompt))
    todo, skipped = [], []
    for job in jobs:
        name = transcript_name(job[0], job[1], job[2])
        (todo if args.overwrite or needs_run(folder / name) else skipped).append(job)
    for qid, condition, run, _ in skipped:
        print(f"{transcript_name(qid, condition, run)}: finished, skipped")

    version = subprocess.run(
        ["claude", "--version"], capture_output=True, text=True, check=True
    ).stdout.strip()
    meta["invocations"].append(
        invocation(
            memex_commit=_git_commit(REPO),
            claude_version=version,
            argv=sys.argv[1:] if argv is None else list(argv),
            started=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            env_removed=removed,
            jobs=[transcript_name(q, c, r) for q, c, r, _ in todo],
        )
    )
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    for qid, condition, run, prompt in todo:
        out = folder / transcript_name(qid, condition, run)
        print(f"{out.name}: running", flush=True)
        argv_ = command(condition, config, root, REPO)
        _call(argv_, prompt, out, workdir, config.timeout_s, env)
        print(f"{out.name}: {_status(out, condition)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
