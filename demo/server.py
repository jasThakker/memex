"""Memex demo: the code graph as an interactive page, with a chat answered by Claude Code.

    uv run python demo/server.py            # then open http://127.0.0.1:8765

Needs Neo4j running with at least one codebase indexed (`uv run memex index mealie`). The
chat runs headless Claude Code (`claude -p`) with only the Memex MCP tools and Read, so it
needs the `claude` CLI logged in; each question costs a few cents.

Not part of the `memex` package: a demo on top of it. It reads the graph with one export
query of its own and reuses `memex.query` for everything else. Standard library only.
"""

import argparse
import json
import os
import subprocess
import tempfile
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from neo4j import Driver, RoutingControl

from memex.config import Registry, UnknownCodebaseError, load_config
from memex.graph.store import connect
from memex.query.codebases import list_codebases
from memex.query.impact import impact_of

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PAGE = HERE / "index.html"

MODEL = "claude-sonnet-5-5"
EFFORT = "medium"
MAX_BUDGET_USD = 1.0
TIMEOUT_S = 300
# A child claude must not inherit this session's identity, MCP tuning or model overrides
# (the same list as eval/run.py).
ENV_PREFIXES = (
    "CLAUDE",
    "MCP_",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_",
    "ANTHROPIC_SMALL_FAST_MODEL",
)

PROMPT = """\
You are a guide to the Python codebase `{codebase}`, indexed in a code knowledge graph that
you query with the memex tools. Always pass codebase="{codebase}". The source is at {root}
if you need to Read a few lines, but prefer the graph tools.

Answer the question below for a developer, in plain English, in at most 150 words. Name
code by its full dotted qualname in backticks (for example `pkg.module.Class.method`), so it
can be highlighted. Mention how sure you are when the graph may be incomplete.

Question: {question}
"""

_NODES = (
    "MATCH (n {codebase: $codebase}) "
    "WHERE n:Module OR n:Class OR n:Function OR n:Doc "
    "RETURN n.id AS id, labels(n)[0] AS label, properties(n) AS p"
)
_LINKS = (
    "MATCH (a {codebase: $codebase})-[r]->(b) "
    "WHERE (a:Module OR a:Class OR a:Function OR a:Doc) "
    "AND (b:Module OR b:Class OR b:Function) "
    "RETURN a.id AS s, b.id AS t, type(r) AS k"
)


def export_graph(driver: Driver, codebase: str) -> dict[str, Any]:
    """Every Module, Class, Function and Doc node of one codebase and the edges between them.

    External nodes are left out: they are outside the codebase and would only add noise."""
    rows, _, _ = driver.execute_query(_NODES, codebase=codebase, routing_=RoutingControl.READ)
    nodes = []
    for row in rows:
        p, label = row["p"], row["label"]
        if label == "Doc":
            title = p.get("anchor") or Path(p["path"]).name
            nodes.append(
                {
                    "id": row["id"],
                    "kind": "doc",
                    "name": title,
                    "q": f"{p['path']}#{p.get('anchor', '')}",
                    "path": p["path"],
                    "line": p.get("start_line"),
                    "layer": "docs",
                    "info": p.get("heading_path") or p["path"],
                    "doc_kind": p.get("kind"),
                }
            )
            continue
        qualname = p["qualname"]
        nodes.append(
            {
                "id": row["id"],
                "kind": label.lower(),
                "name": p.get("name") or qualname.rsplit(".", 1)[-1],
                "q": qualname,
                "path": p.get("path"),
                "line": p.get("line"),
                "layer": p.get("layer"),
                "domain": p.get("domain"),
                "info": p.get("signature") or p.get("docstring"),
                "docstring": p.get("docstring"),
            }
        )
    rows, _, _ = driver.execute_query(_LINKS, codebase=codebase, routing_=RoutingControl.READ)
    links = [{"source": row["s"], "target": row["t"], "kind": row["k"]} for row in rows]
    return {"codebase": codebase, "nodes": nodes, "links": links}


def impact(driver: Driver, codebase: str, qualname: str, depth: int) -> dict[str, Any]:
    """The impact set of one symbol as {id: distance}, with each dependent's edge path."""
    result = impact_of(driver, codebase, qualname, max_depth=depth, limit=200)
    dependents = [d for group in result.layers for d in group.dependents]
    return {
        "symbol": result.symbol.qualname if result.symbol else None,
        "total": result.total,
        "truncated": result.truncated,
        "dependents": [
            {
                "id": f"{codebase}:{d.symbol.qualname}",
                "q": d.symbol.qualname,
                "distance": d.distance,
                "path": [{"edge": step.edge, "to": f"{codebase}:{step.to}"} for step in d.path],
            }
            for d in dependents
        ],
        "docs": [doc.model_dump() for doc in result.docs],
    }


def chat_command(codebase: str) -> list[str]:
    server = {"command": "uv", "args": ["--directory", str(REPO), "run", "memex", "serve"]}
    return [
        "claude",
        "-p",
        "--model",
        MODEL,
        "--effort",
        EFFORT,
        "--output-format",
        "stream-json",
        "--verbose",
        "--strict-mcp-config",
        "--mcp-config",
        json.dumps({"mcpServers": {"memex": server}}),
        "--tools",
        "Read",
        "--allowedTools",
        "Read,mcp__memex",
        "--permission-mode",
        "dontAsk",
        "--no-session-persistence",
        "--max-budget-usd",
        str(MAX_BUDGET_USD),
    ]


def chat(registry: Registry, codebase: str, question: str) -> Iterator[dict[str, Any]]:
    """Runs one question through `claude -p` and yields events as they happen:
    tool (a Memex call), symbols (qualnames its results named), text, done or error."""
    root = registry.get(codebase).root
    prompt = PROMPT.format(codebase=codebase, root=root, question=question.strip()[:1000])
    env = {k: v for k, v in os.environ.items() if not k.startswith(ENV_PREFIXES)}
    # An empty working directory outside the repo, so no CLAUDE.md is loaded.
    with tempfile.TemporaryDirectory(prefix="memex-demo-") as workdir:
        argv = [*chat_command(codebase), "--add-dir", str(root)]
        try:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=workdir,
                env=env,
                text=True,
            )
        except FileNotFoundError:
            yield {"type": "error", "message": "the `claude` CLI is not on PATH"}
            return
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(prompt)
        process.stdin.close()
        finished = False
        for line in process.stdout:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            for out in _translate(event):
                finished = finished or out["type"] in ("done", "error")
                yield out
        process.wait(timeout=TIMEOUT_S)
        if not finished:
            stderr = process.stderr.read() if process.stderr else ""
            yield {"type": "error", "message": stderr.strip()[-500:] or "claude exited early"}


def _translate(event: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """One stream-json event from claude as zero or more demo events."""
    kind = event.get("type")
    if kind == "assistant":
        for part in event.get("message", {}).get("content", []):
            if part.get("type") == "tool_use":
                name = str(part.get("name", "")).removeprefix("mcp__memex__")
                yield {"type": "tool", "name": name, "input": part.get("input", {})}
    elif kind == "user":
        for part in event.get("message", {}).get("content", []):
            if isinstance(part, dict) and part.get("type") == "tool_result":
                names = sorted(_qualnames(part.get("content")))
                if names:
                    yield {"type": "symbols", "qualnames": names}
    elif kind == "result":
        if event.get("is_error"):
            yield {"type": "error", "message": str(event.get("result") or "the run failed")}
            return
        yield {"type": "text", "text": event.get("result", "")}
        yield {
            "type": "done",
            "cost_usd": event.get("total_cost_usd"),
            "duration_ms": event.get("duration_ms"),
            "turns": event.get("num_turns"),
        }


def _qualnames(content: Any) -> set[str]:
    """Every `qualname` value inside a tool result's JSON text."""
    found: set[str] = set()
    texts: list[str] = []
    if isinstance(content, str):
        texts.append(content)
    elif isinstance(content, list):
        texts.extend(c.get("text", "") for c in content if isinstance(c, dict))
    stack: list[Any] = []
    for text in texts:
        try:
            stack.append(json.loads(text))
        except json.JSONDecodeError:
            continue
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if isinstance(value.get("qualname"), str):
                found.add(value["qualname"])
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return found


def make_handler(driver: Driver, registry: Registry) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # quieter console
            if not self.path.startswith("/api/graph"):
                super().log_message(format, *args)

        def do_GET(self) -> None:
            url = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                if url.path in ("/", "/index.html"):
                    self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
                elif url.path == "/api/codebases":
                    self._json(list_codebases(driver, registry).model_dump())
                elif url.path == "/api/graph":
                    self._json(export_graph(driver, self._codebase(query)))
                elif url.path == "/api/impact":
                    depth = max(1, min(5, int(query.get("depth", "3"))))
                    self._json(impact(driver, self._codebase(query), query["symbol"], depth))
                else:
                    self._json({"error": "not found"}, 404)
            except (KeyError, ValueError, UnknownCodebaseError) as error:
                self._json({"error": str(error)}, 400)

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/api/chat":
                self._json({"error": "not found"}, 404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                codebase = self._codebase(body)
                question = str(body["question"])
            except (KeyError, ValueError, UnknownCodebaseError) as error:
                self._json({"error": str(error)}, 400)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            for event in chat(registry, codebase, question):
                self.wfile.write((json.dumps(event) + "\n").encode())
                self.wfile.flush()

        def _codebase(self, source: dict[str, Any]) -> str:
            name = str(source["codebase"])
            registry.get(name)  # raises for an unregistered name
            return name

        def _json(self, value: Any, status: int = 200) -> None:
            self._send(status, json.dumps(value).encode(), "application/json")

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--config", type=Path, default=REPO / "memex.toml")
    args = parser.parse_args()
    registry = load_config(args.config)
    driver = connect()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(driver, registry))
    print(f"Memex demo on http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        driver.close()


if __name__ == "__main__":
    main()
