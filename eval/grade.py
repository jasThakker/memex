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
ANSWER_BLOCK = re.compile(r"```json[ \t]*\n(.*?)```", re.DOTALL | re.IGNORECASE)
TRANSCRIPT_NAME = re.compile(r"^(?P<qid>q\d+|baseline)-(?P<condition>[A-Z])-(?P<run>\d+)\.jsonl$")
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
        value = data.get(key, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return None
        lists[key] = tuple(value)
    return Answer(symbols=lists["symbols"], docs=lists["docs"])


def _clean(text: str) -> str:
    return " ".join(text.strip().strip("`").split())


def normalize_symbol(text: str) -> str:
    """Backticks, a trailing () and case do not count."""
    cleaned = _clean(text)
    cleaned = cleaned.removesuffix("()")
    return cleaned.lower()


def normalize_doc(text: str, root: str) -> str:
    """path#Heading relative to root; a heading path keeps only its last heading."""
    cleaned = _clean(text)
    prefix = root.rstrip("/") + "/"
    if root and cleaned.startswith(prefix):
        cleaned = cleaned.removeprefix(prefix)
    cleaned = cleaned.removeprefix("./")
    path, hash_, heading = cleaned.partition("#")
    if hash_:
        heading = heading.split(" > ")[-1].strip()
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
    """Read stream-json lines from `claude -p --output-format stream-json --verbose`."""
    tools: tuple[str, ...] = ()
    servers: tuple[tuple[str, str], ...] = ()
    calls: list[str] = []
    result: dict[str, Any] | None = None
    for line in lines:
        if not line.strip():
            continue
        event = json.loads(line)
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            tools = tuple(event.get("tools", []))
            servers = tuple((s["name"], s.get("status", "")) for s in event.get("mcp_servers", []))
        elif kind == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    calls.append(block["name"])
        elif kind == "result":
            result = event
    if result is None:
        return Transcript(tools=tools, mcp_servers=servers, tool_calls=tuple(calls))
    usage = result.get("usage", {})
    return Transcript(
        tools=tools,
        mcp_servers=servers,
        tool_calls=tuple(calls),
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


# Summary


def usage_dict(usages: Iterable[Usage]) -> dict[str, Any]:
    """Usage summed over runs, with total_input."""
    items = list(usages)
    totals: dict[str, Any] = {name: sum(getattr(u, name) for u in items) for name in USAGE_FIELDS}
    totals["cost_usd"] = round(totals["cost_usd"], 6)
    return totals


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per condition: mean combined P, R and F1, mean F1 by category, usage summed."""
    summary: dict[str, dict[str, Any]] = {}
    for condition in sorted({row["condition"] for row in rows}):
        mine = [row for row in rows if row["condition"] == condition]
        grades = [row["grade"] for row in mine]
        categories = sorted({row["question"]["category"] for row in mine})
        summary[condition] = {
            "runs": len(mine),
            "answered": sum(grade.answered for grade in grades),
            "errors": sum(row["transcript"].is_error for row in mine),
            "precision": mean(grade.combined.precision for grade in grades),
            "recall": mean(grade.combined.recall for grade in grades),
            "f1": mean(grade.combined.f1 for grade in grades),
            "by_category": {
                category: mean(
                    row["grade"].combined.f1
                    for row in mine
                    if row["question"]["category"] == category
                )
                for category in categories
            },
            "usage": usage_dict(row["transcript"].usage for row in mine),
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
        question = questions[match["qid"]]
        rows.append(
            {
                "question": question,
                "condition": match["condition"],
                "run": int(match["run"]),
                "grade": grade_question(question, transcript.result_text, root),
                "transcript": transcript,
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
            **asdict(row["grade"]),
            "usage": usage_dict([row["transcript"].usage]),
            "tool_calls": dict(sorted(Counter(row["transcript"].tool_calls).items())),
        }
        for row in graded["rows"]
    ]
    baselines = {
        condition: {
            "error": transcript.is_error,
            "tools": list(transcript.tools),
            "mcp_servers": [list(server) for server in transcript.mcp_servers],
            "usage": usage_dict([transcript.usage]),
        }
        for condition, transcript in sorted(graded["baselines"].items())
    }
    data = {"summary": graded["summary"], "baselines": baselines, "runs": runs}
    return json.dumps(data, indent=2) + "\n"


def _f(value: float) -> str:
    return f"{value:.2f}"


def results_md(graded: dict[str, Any]) -> str:
    meta, summary, rows = graded["meta"], graded["summary"], graded["rows"]
    out = [f"# Eval run {meta.get('name', '')}", ""]
    out += [
        f"- Model: `{meta.get('model', '')}`; Claude Code `{meta.get('claude_version', '')}`",
        f"- Memex commit `{meta.get('memex_commit', '')}`; codebase commit "
        f"`{meta.get('codebase_commit', '')}`",
        f"- Runs per condition: {meta.get('runs_per_condition', 1)}"
        + (" (N=1: no variance estimate)" if meta.get("runs_per_condition", 1) == 1 else ""),
        "- Score: precision, recall and F1 over the combined set of expected symbols and docs, "
        "averaged over questions.",
        "",
        "## Summary",
        "",
        "| Condition | Runs | Answered | Errors | P | R | F1 | Input (all) | Uncached | "
        "Cache write | Cache read | Output | Cost USD | Turns | Time s |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for condition, s in summary.items():
        u = s["usage"]
        out.append(
            f"| {condition} | {s['runs']} | {s['answered']} | {s['errors']} | "
            f"{_f(s['precision'])} | {_f(s['recall'])} | {_f(s['f1'])} | {u['total_input']:,} | "
            f"{u['input_tokens']:,} | {u['cache_creation_tokens']:,} | "
            f"{u['cache_read_tokens']:,} | {u['output_tokens']:,} | {u['cost_usd']:.2f} | "
            f"{u['turns']} | {u['duration_ms'] / 1000:.0f} |"
        )
    categories = sorted({c for s in summary.values() for c in s["by_category"]})
    conditions = list(summary)
    out += ["", "## F1 by category", ""]
    out += ["| Category | " + " | ".join(conditions) + " |", "|---" * (len(conditions) + 1) + "|"]
    for category in categories:
        cells = [_f(summary[c]["by_category"].get(category, 0.0)) for c in conditions]
        out.append(f"| {category} | " + " | ".join(cells) + " |")

    baselines: dict[str, Transcript] = graded["baselines"]
    if baselines:
        out += ["", "## Fixed cost per call (baseline prompt, no question)", ""]
        out += ["| Condition | Input (all) | Tools offered | MCP servers |", "|---|---|---|---|"]
        for condition, t in sorted(baselines.items()):
            servers = ", ".join(f"{name} ({status})" for name, status in t.mcp_servers) or "none"
            out.append(f"| {condition} | {t.usage.total_input:,} | {len(t.tools)} | {servers} |")
        if {"A", "B"} <= baselines.keys():
            diff = baselines["B"].usage.total_input - baselines["A"].usage.total_input
            out += ["", f"Condition B pays {diff:+,} input tokens per call before any work."]

    out += ["", "## Per question", ""]
    out += [
        "| Question | Category | Condition | F1 | P | R | Input (all) | Output | Turns "
        "| Tool calls |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        g, u = row["grade"], row["transcript"].usage
        counts = sorted(Counter(row["transcript"].tool_calls).items())
        calls = ", ".join(f"{name} x{count}" for name, count in counts)
        flag = "" if g.answered else " (no answer block)"
        if row["transcript"].is_error:
            flag += " (error)"
        out.append(
            f"| {row['question']['id']}{flag} | {row['question']['category']} | "
            f"{row['condition']} | {_f(g.combined.f1)} | {_f(g.combined.precision)} | "
            f"{_f(g.combined.recall)} | {u.total_input:,} | {u.output_tokens:,} | {u.turns} | "
            f"{calls} |"
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
    graded = grade_run(args.folder, load_questions(args.questions))
    (args.folder / "scores.json").write_text(scores_json(graded), encoding="utf-8")
    (args.folder / "results.md").write_text(results_md(graded), encoding="utf-8")
    print(f"wrote {args.folder / 'scores.json'} and {args.folder / 'results.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
