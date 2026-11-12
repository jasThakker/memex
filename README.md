# memex

A knowledge graph over any Python codebase and its docs, served to coding agents by a read-only MCP server. Design: [DESIGN.md](DESIGN.md). History: [DEVLOG.md](DEVLOG.md).

## How to run

Needs [uv](https://docs.astral.sh/uv/) and Docker.

```sh
uv sync                                        # Python 3.14 and dependencies
docker compose up -d neo4j                     # Neo4j at bolt://localhost:7687
uv run python scripts/fetch_codebases.py       # benchmark repos into vendor/ (optional)
uv run memex index httpx                       # any codebase registered in memex.toml
uv run memex stats httpx
```

Then start Claude Code in this folder. `.mcp.json` registers the server (`uv run memex serve`); approve it when asked, or check it with `/mcp`. Ask, for example, "In httpx, what calls `Client.request`?".

The tools: `list_codebases`, `find_symbol`, `callers`, `callees`, `impact_of`, `search_docs`. Every tool except `list_codebases` takes the codebase name explicitly. Before a change, the server instructions tell the agent to call `impact_of` on each symbol it will change and `search_docs` on a description of the change, read the cited doc sections and judge for itself (ADR-004); Memex finds and cites, the agent decides.

To index another repo, add a section to `memex.toml` (`root` and `packages` are enough) and run `uv run memex index <name>`.

Neo4j settings come from `NEO4J_URI`, `NEO4J_USER` and `NEO4J_PASSWORD` (defaults match `docker-compose.yml`).

## Demo UI

```sh
uv run python demo/server.py                   # then open http://127.0.0.1:8765
```

An interactive map of an indexed codebase: every module, class, function and doc section as a node, grouped by layer, with edge types you can switch on and off. Hover to see a node's neighbours, click to inspect it, drag to pin it, press `/` to search, and use **Trace impact** to light up everything that depends on it within three hops. The chat at the bottom sends a question to headless Claude Code (`claude -p`) with only the Memex tools. It shows each tool call as it happens and highlights the symbols the answer names. The chat needs the `claude` CLI logged in; a question takes a few seconds and costs a few cents. The page loads fonts and two small libraries from public CDNs.

## Evaluation

Twelve questions about Mealie with hand-verified answers (`eval/questions.yaml`), each asked in two conditions with the same model and prompt: **A** with `Read`, `Grep` and `Glob`, **B** with the Memex tools and `Read`. Details: DESIGN.md section 14.

```sh
uv run memex index mealie                      # needs vendor/ and Neo4j
uv run python eval/run.py --name <run> --baseline
uv run python eval/grade.py eval/results/<run>
```

Results of the committed run (`eval/results/full/results.md`; `claude-sonnet-5-5`, effort high, one run per condition):

| Condition | F1 | Precision | Recall | Input tokens | Cost | Time |
|---|---|---|---|---|---|---|
| A: file search | 0.68 | 0.64 | 0.79 | 502k | $0.71 | 177 s |
| B: Memex | 0.60 | 0.54 | 0.76 | 701k | $0.80 | 180 s |

- On these mostly one-hop questions, Memex found about as much as file search (recall 0.76 vs 0.79), with more extra items, in the same time, at 13% more cost.
- It did best on callers and dependents.
- It lost most on the doc questions, and on a call graph that misses calls through injected attributes, which sent the agent back to reading files.

DEVLOG.md (Phase 7) has the per-question analysis. Phase 9 then checked `impact_of` by hand on four Mealie symbols (`eval/impact_check.md`): precision was 1.00 and recall was the gap, which three fixes closed (for example, direct dependents of `get_current_user` went from 5 of 10 to 10 of 10). The eval above was not re-run after those fixes.

## Tests

```sh
uv run pytest                                  # unit tests, no database
uv run pytest -m "neo4j and not realrepo"      # query and MCP tests, needs Docker
uv run pytest -m realrepo                      # benchmark repos, needs vendor/ and Docker
```
