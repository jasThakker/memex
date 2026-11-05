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

The tools: `list_codebases`, `find_symbol`, `callers`, `callees`, `impact_of`, `search_docs`, `check_change`. Every tool except `list_codebases` takes the codebase name explicitly. `check_change` takes a proposed change (a description, optionally its symbols) and returns the code it affects and the documented rules that apply, each quoted and cited.

To index another repo, add a section to `memex.toml` (`root` and `packages` are enough) and run `uv run memex index <name>`.

Neo4j settings come from `NEO4J_URI`, `NEO4J_USER` and `NEO4J_PASSWORD` (defaults match `docker-compose.yml`).

## Tests

```sh
uv run pytest                                  # unit tests, no database
uv run pytest -m "neo4j and not realrepo"      # query and MCP tests, needs Docker
uv run pytest -m realrepo                      # benchmark repos, needs vendor/ and Docker
```
