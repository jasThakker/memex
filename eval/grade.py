"""Grade one eval run (DESIGN.md section 14): deterministic set scores, no LLM.

Usage: uv run python eval/grade.py eval/results/<run>

Reads the run folder written by eval/run.py (meta.json plus one stream-json transcript per
question, condition and repetition, named <qid>-<condition>-<n>.jsonl, and baseline-<condition>-1
.jsonl for the tool-definition overhead) and writes scores.json and results.md next to them.
"""

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any

import yaml

QUESTIONS = Path(__file__).resolve().parent / "questions.yaml"
ANSWER_BLOCK = re.compile(r"```json(?![\w-])[ \t]*\n?(.*?)```", re.DOTALL | re.IGNORECASE)
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
CONDITION_A_TOOLS = frozenset({"Read", "Grep", "Glob"})
GRAPH_SERVER = "memex"
TRANSCRIPT_NAME = re.compile(
    r"^(?P<qid>[a-z]\d+|baseline)-(?P<condition>[A-Z])-(?P<run>\d+)\.jsonl$"
)
USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_tokens",
    "cache_read_tokens",
    "total_input",
    "cost_usd",
    "turns",
    "duration_ms",
)


@dataclass(frozen=True)
class Answer:
    symbols: tuple[str, ...] = ()
    docs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Score:
    precision: float
    recall: float
    f1: float


@dataclass(frozen=True)
class Grade:
    answered: bool
    symbols: Score
    docs: Score
    combined: Score
    missed: tuple[str, ...]  # expected items not given, original spelling, sorted
    extra: tuple[str, ...]  # given items not expected, first spelling, sorted


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    turns: int = 0
    duration_ms: int = 0

    @property
    def total_input(self) -> int:
        """Every input token the model read, cached or not."""
        return self.input_tokens + self.cache_creation_tokens + self.cache_read_tokens


@dataclass(frozen=True)
class Transcript:
    tools: tuple[str, ...] = ()  # tools offered, from the init event
    mcp_servers: tuple[tuple[str, str], ...] = ()  # (name, status) from the init event
    tool_calls: tuple[str, ...] = ()  # tool names called, in order
    result_text: str = ""
    is_error: bool = True
    usage: Usage = field(default_factory=Usage)
    has_init: bool = False
    bad_lines: int = 0  # lines that are not JSON, such as one cut off by a timeout
    estimated: bool = False  # no result event: usage summed from the assistant messages


# Answers


def extract_answer(text: str) -> Answer | None:
    """The last fenced json block as an Answer, or None when there is no valid one."""
    blocks = ANSWER_BLOCK.findall(text)
    if not blocks:
        return None
    try:
        data = json.loads(blocks[-1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    lists: dict[str, tuple[str, ...]] = {}
    for key in ("symbols", "docs"):
        value = data.get(key) or []
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return None
        lists[key] = tuple(value)
    return Answer(symbols=lists["symbols"], docs=lists["docs"])


def _clean(text: str) -> str:
    return " ".join(text.strip().strip("`").split())


def normalize_symbol(text: str) -> str:
    """Backticks, a trailing () and case do not count."""
    cleaned = _clean(text).removesuffix("()").strip("`")
    return cleaned.removesuffix("()").lower()


def normalize_doc(text: str, root: str) -> str:
    """path#Heading relative to root, compared as plain text: a heading path keeps only its
    last heading, Markdown links keep their text, and leading # marks are dropped."""
    cleaned = _clean(LINK.sub(r"\1", text))
    prefix = root.rstrip("/") + "/"
    if root and cleaned.startswith(prefix):
        cleaned = cleaned.removeprefix(prefix)
    cleaned = cleaned.removeprefix("./")
    path, hash_, heading = cleaned.partition("#")
    if hash_:
        heading = heading.split(" > ")[-1].lstrip("#").strip()
        return f"{path.strip()}#{heading}".lower()
    return path.lower()


# Scores


def score(expected: set[str], got: set[str]) -> Score:
    """Precision, recall and F1. Nothing expected and nothing given is a perfect score."""
    if not expected and not got:
        return Score(precision=1.0, recall=1.0, f1=1.0)
    hits = len(expected & got)
    precision = hits / len(got) if got else 0.0
    recall = hits / len(expected) if expected else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return Score(precision=precision, recall=recall, f1=f1)


def _spellings(items: Iterable[str], normalize: Any) -> dict[str, str]:
    """Normalized form -> the first original spelling."""
    seen: dict[str, str] = {}
    for item in items:
        seen.setdefault(normalize(item), item.strip())
    return seen


def grade_question(question: dict[str, Any], answer_text: str, root: str) -> Grade:
    """Score one answer against the question's expected symbols and docs."""
    expected = question["expected"]
    answer = extract_answer(answer_text)
    given = answer or Answer()

    def doc_key(text: str) -> str:
        return normalize_doc(text, root)

    want_symbols = _spellings(expected.get("symbols") or [], normalize_symbol)
    want_docs = _spellings(expected.get("docs") or [], doc_key)
    got_symbols = _spellings(given.symbols, normalize_symbol)
    got_docs = _spellings(given.docs, doc_key)

    want = {f"s:{k}": v for k, v in want_symbols.items()} | {
        f"d:{k}": v for k, v in want_docs.items()
    }
    got = {f"s:{k}": v for k, v in got_symbols.items()} | {f"d:{k}": v for k, v in got_docs.items()}
    return Grade(
        answered=answer is not None,
        symbols=score(set(want_symbols), set(got_symbols)),
        docs=score(set(want_docs), set(got_docs)),
        combined=score(set(want), set(got)),
        missed=tuple(sorted(want[key] for key in want.keys() - got.keys())),
        extra=tuple(sorted(got[key] for key in got.keys() - want.keys())),
    )


# Transcripts


def read_transcript(lines: Iterable[str]) -> Transcript:
    """Read stream-json lines from `claude -p --output-format stream-json --verbose`.

    A line that is not JSON is counted, not fatal. With no result event, usage is summed from
    the assistant messages (the last usage seen per message id) and marked as estimated.
    """
    tools: tuple[str, ...] = ()
    servers: tuple[tuple[str, str], ...] = ()
    has_init = False
    bad_lines = 0
    calls: list[str] = []
    message_usage: dict[str, dict[str, int]] = {}
    result: dict[str, Any] | None = None
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            bad_lines += 1
            continue
        if not isinstance(event, dict):
            bad_lines += 1
            continue
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            has_init = True
            tools = tuple(event.get("tools", []))
            servers = tuple((s["name"], s.get("status", "")) for s in event.get("mcp_servers", []))
        elif kind == "assistant":
            message = event.get("message", {})
            for block in message.get("content", []):
                if block.get("type") == "tool_use":
                    calls.append(block["name"])
            if message.get("id") and message.get("usage"):
                message_usage[message["id"]] = message["usage"]
        elif kind == "result":
            result = event
    common = {
        "tools": tools,
        "mcp_servers": servers,
        "tool_calls": tuple(calls),
        "has_init": has_init,
        "bad_lines": bad_lines,
    }
    if result is None:
        usages = list(message_usage.values())
        return Transcript(
            **common,
            estimated=bool(usages),
            usage=Usage(
                input_tokens=sum(u.get("input_tokens", 0) for u in usages),
                output_tokens=sum(u.get("output_tokens", 0) for u in usages),
                cache_creation_tokens=sum(u.get("cache_creation_input_tokens", 0) for u in usages),
                cache_read_tokens=sum(u.get("cache_read_input_tokens", 0) for u in usages),
                turns=len(usages),
            ),
        )
    usage = result.get("usage", {})
    return Transcript(
        **common,
        result_text=result.get("result", "") or "",
        is_error=bool(result.get("is_error")) or result.get("subtype") != "success",
        usage=Usage(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
            cache_read_tokens=usage.get("cache_read_input_tokens", 0),
            cost_usd=result.get("total_cost_usd", 0.0),
            turns=result.get("num_turns", 0),
            duration_ms=result.get("duration_ms", 0),
        ),
    )


def check_tools(condition: str, transcript: Transcript) -> str | None:
    """None when the init event offered exactly the condition's tools, else the problem.

    A: Read, Grep and Glob, and no MCP server. B: Read plus the graph server's tools, with
    that server connected and no other.
    """
    if not transcript.has_init:
        return "no init event"
    tools = set(transcript.tools)
    servers = dict(transcript.mcp_servers)
    others = sorted(set(servers) - {GRAPH_SERVER}) if condition == "B" else sorted(servers)

    def tool_problem(wanted: set[str], allowed_prefix: str | None) -> str | None:
        missing = sorted(wanted - tools)
        unexpected = sorted(
            t for t in tools - wanted if not (allowed_prefix and t.startswith(allowed_prefix))
        )
        parts = []
        if missing:
            parts.append("missing " + ", ".join(missing))
        if unexpected:
            parts.append("unexpected " + ", ".join(unexpected))
        return "tools: " + "; ".join(parts) if parts else None

    if condition == "A":
        problem = tool_problem(set(CONDITION_A_TOOLS), None)
        if problem:
            return problem
        return "mcp: " + ", ".join(others) if others else None
    if condition == "B":
        if GRAPH_SERVER not in servers:
            return f"{GRAPH_SERVER} missing"
        if servers[GRAPH_SERVER] != "connected":
            return f"{GRAPH_SERVER} {servers[GRAPH_SERVER]}"
        if others:
            return "mcp: " + ", ".join(others)
        prefix = f"mcp__{GRAPH_SERVER}__"
        problem = tool_problem({"Read"}, prefix)
        if problem:
            return problem
        if not any(t.startswith(prefix) for t in tools):
            return f"tools: no {prefix} tools"
        return None
    raise ValueError(f"unknown condition {condition!r}")


# Summary


def usage_dict(usages: Iterable[Usage]) -> dict[str, Any]:
    """Usage summed over runs, with total_input."""
    items = list(usages)
    totals: dict[str, Any] = {name: sum(getattr(u, name) for u in items) for name in USAGE_FIELDS}
    totals["cost_usd"] = round(totals["cost_usd"], 6)
    return totals


def _means(rows: Sequence[dict[str, Any]]) -> dict[str, float | None]:
    grades = [row["grade"].combined for row in rows]
    if not grades:
        return {"precision": None, "recall": None, "f1": None}
    return {
        "precision": mean(g.precision for g in grades),
        "recall": mean(g.recall for g in grades),
        "f1": mean(g.f1 for g in grades),
    }


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per condition: mean combined P, R and F1 overall and by category over the valid runs,
    and usage summed over every run, valid or not (its tokens were spent either way).

    A row is invalid when it has a `problem` (its tools did not match the condition)."""
    summary: dict[str, dict[str, Any]] = {}
    for condition in sorted({row["condition"] for row in rows}):
        mine = [row for row in rows if row["condition"] == condition]
        valid = [row for row in mine if not row.get("problem")]
        categories = sorted({row["question"]["category"] for row in mine})
        summary[condition] = {
            "runs": len(mine),
            "invalid": len(mine) - len(valid),
            "answered": sum(row["grade"].answered for row in valid),
            "errors": sum(row["transcript"].is_error for row in mine),
            **_means(valid),
            "by_category": {
                category: _means([r for r in valid if r["question"]["category"] == category])
                for category in categories
            },
            "usage": usage_dict(row["transcript"].usage for row in mine),
            "estimated_usage": sum(row["transcript"].estimated for row in mine),
        }
    return summary


# Run folder -> scores.json and results.md


def load_questions(path: Path = QUESTIONS) -> dict[str, dict[str, Any]]:
    return {question["id"]: question for question in yaml.safe_load(path.read_text("utf-8"))}


def _read(path: Path) -> Transcript:
    return read_transcript(path.read_text(encoding="utf-8").splitlines())


def grade_run(folder: Path, questions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Grade every transcript in a run folder."""
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    root = meta["root"]
    rows: list[dict[str, Any]] = []
    baselines: dict[str, Transcript] = {}
    for path in sorted(folder.glob("*.jsonl")):
        match = TRANSCRIPT_NAME.match(path.name)
        if match is None:
            continue
        transcript = _read(path)
        if match["qid"] == "baseline":
            baselines[match["condition"]] = transcript
            continue
        if match["qid"] not in questions:
            raise ValueError(f"{path.name}: question {match['qid']} is not in the questions file")
        question = questions[match["qid"]]
        rows.append(
            {
                "question": question,
                "condition": match["condition"],
                "run": int(match["run"]),
                "grade": grade_question(question, transcript.result_text, root),
                "transcript": transcript,
                "problem": check_tools(match["condition"], transcript),
            }
        )
    return {"meta": meta, "rows": rows, "baselines": baselines, "summary": summarize(rows)}


def scores_json(graded: dict[str, Any]) -> str:
    runs = [
        {
            "id": row["question"]["id"],
            "category": row["question"]["category"],
            "condition": row["condition"],
            "run": row["run"],
            "error": row["transcript"].is_error,
            "problem": row["problem"],
            "bad_lines": row["transcript"].bad_lines,
            "estimated_usage": row["transcript"].estimated,
            **asdict(row["grade"]),
            "usage": usage_dict([row["transcript"].usage]),
            "tool_calls": dict(sorted(Counter(row["transcript"].tool_calls).items())),
        }
        for row in graded["rows"]
    ]
    baselines = {
        condition: {
            "error": transcript.is_error,
            "problem": check_tools(condition, transcript),
            "tools": list(transcript.tools),
            "mcp_servers": [list(server) for server in transcript.mcp_servers],
            "usage": usage_dict([transcript.usage]),
        }
        for condition, transcript in sorted(graded["baselines"].items())
    }
    data = {"summary": graded["summary"], "baselines": baselines, "runs": runs}
    return json.dumps(data, indent=2) + "\n"


def _f(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _unique(invocations: list[dict[str, Any]], key: str) -> list[str]:
    return list(dict.fromkeys(str(inv.get(key, "")) for inv in invocations))


def results_md(graded: dict[str, Any]) -> str:
    meta, summary, rows = graded["meta"], graded["summary"], graded["rows"]
    invocations = meta.get("invocations", [])
    commits = _unique(invocations, "memex_commit")
    versions = _unique(invocations, "claude_version")
    runs_per_condition = meta.get("runs_per_condition", 1)
    out = [f"# Eval run {meta.get('name', '')}", ""]
    out += [
        f"- Model: `{meta.get('model', '')}`, effort `{meta.get('effort', '')}`; Claude Code "
        + ", ".join(f"`{v}`" for v in versions),
        "- Memex commit "
        + ", ".join(f"`{c}`" for c in commits)
        + (" (mixed: transcripts come from different commits)" if len(commits) > 1 else "")
        + f"; codebase commit `{meta.get('codebase_commit', '')}`",
        f"- Invocations of eval/run.py: {len(invocations)} (listed in meta.json)",
        f"- Runs per condition: {runs_per_condition}"
        + (" (N=1: no variance estimate)" if runs_per_condition == 1 else ""),
        "- Score: precision, recall and F1 over the combined set of expected symbols and docs, "
        "averaged over the valid runs. A run is invalid when its init event did not offer "
        "exactly the condition's tools; its tokens still count in the usage columns.",
        "",
        "## Summary",
        "",
        "| Condition | Runs | Invalid | Answered | Errors | P | R | F1 | Input (all) | "
        "Uncached | Cache write | Cache read | Output | Cost USD | Turns | Time s |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for condition, c in summary.items():
        u = c["usage"]
        out.append(
            f"| {condition} | {c['runs']} | {c['invalid']} | {c['answered']} | {c['errors']} | "
            f"{_f(c['precision'])} | {_f(c['recall'])} | {_f(c['f1'])} | {u['total_input']:,} | "
            f"{u['input_tokens']:,} | {u['cache_creation_tokens']:,} | "
            f"{u['cache_read_tokens']:,} | {u['output_tokens']:,} | {u['cost_usd']:.2f} | "
            f"{u['turns']} | {u['duration_ms'] / 1000:.0f} |"
        )
    estimated = sum(c["estimated_usage"] for c in summary.values())
    if estimated:
        out += [
            "",
            f"{estimated} run(s) ended without a result event: their tokens are summed from "
            "the assistant messages and their cost and time are unknown (counted as 0).",
        ]

    categories = sorted({cat for c in summary.values() for cat in c["by_category"]})
    conditions = list(summary)
    out += ["", "## By category (P / R / F1)", ""]
    out += ["| Category | " + " | ".join(conditions) + " |", "|---" * (len(conditions) + 1) + "|"]
    for category in categories:
        cells = []
        for condition in conditions:
            m = summary[condition]["by_category"].get(category)
            cells.append(
                " / ".join(_f(m[k]) for k in ("precision", "recall", "f1")) if m else "n/a"
            )
        out.append(f"| {category} | " + " | ".join(cells) + " |")

    baselines: dict[str, Transcript] = graded["baselines"]
    if baselines:
        out += ["", "## Fixed cost per request (baseline prompt, no question)", ""]
        out += [
            "| Condition | Input (all) | Tools offered | MCP servers | Check |",
            "|---|---|---|---|---|",
        ]
        for condition, t in sorted(baselines.items()):
            servers = ", ".join(f"{name} ({status})" for name, status in t.mcp_servers) or "none"
            check = check_tools(condition, t) or "ok"
            out.append(
                f"| {condition} | {t.usage.total_input:,} | {len(t.tools)} | {servers} | {check} |"
            )
        if {"A", "B"} <= baselines.keys():
            diff = baselines["B"].usage.total_input - baselines["A"].usage.total_input
            out += [
                "",
                f"Condition B's prompt is {diff:+,} input tokens larger than A's: the graph "
                "tools' definitions and server instructions, minus the Grep and Glob "
                "definitions. It is paid on every request (each turn), mostly as cache reads.",
            ]

    out += ["", "## Per question", ""]
    out += [
        "| Question | Run | Category | Condition | F1 | P | R | Input (all) | Output | Turns "
        "| Tool calls |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        g, t = row["grade"], row["transcript"]
        counts = sorted(Counter(t.tool_calls).items())
        calls = ", ".join(f"{name} x{count}" for name, count in counts)
        flags = []
        if row.get("problem"):
            flags.append(f"invalid: {row['problem']}")
        if not g.answered:
            flags.append("no answer block")
        if t.is_error:
            flags.append("error")
        if t.estimated:
            flags.append("usage estimated")
        if t.bad_lines:
            flags.append(f"{t.bad_lines} bad lines")
        flag = "".join(f" ({f})" for f in flags)
        out.append(
            f"| {row['question']['id']}{flag} | {row['run']} | {row['question']['category']} | "
            f"{row['condition']} | {_f(g.combined.f1)} | {_f(g.combined.precision)} | "
            f"{_f(g.combined.recall)} | {t.usage.total_input:,} | {t.usage.output_tokens:,} | "
            f"{t.usage.turns} | {calls} |"
        )

    out += ["", "## Missed and extra", ""]
    for row in rows:
        g = row["grade"]
        if not g.missed and not g.extra:
            continue
        out.append(f"### {row['question']['id']} {row['condition']} (run {row['run']})")
        out.append("")
        out += [f"- missed: `{item}`" for item in g.missed]
        out += [f"- extra: `{item}`" for item in g.extra]
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path, help="a run folder under eval/results/")
    parser.add_argument("--questions", type=Path, default=QUESTIONS, help="questions YAML")
    args = parser.parse_args(argv)
    if not (args.folder / "meta.json").is_file():
        print(f"error: {args.folder} has no meta.json", file=sys.stderr)
        return 1
    try:
        graded = grade_run(args.folder, load_questions(args.questions))
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    (args.folder / "scores.json").write_text(scores_json(graded), encoding="utf-8")
    (args.folder / "results.md").write_text(results_md(graded), encoding="utf-8")
    print(f"wrote {args.folder / 'scores.json'} and {args.folder / 'results.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
