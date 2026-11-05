"""search_docs (DESIGN.md section 10): full-text search over doc sections of one codebase.

The query is plain text: Lucene syntax characters are escaped and the operator words AND, OR
and NOT are lower-cased, so an agent can paste any sentence or code expression. Terms are
OR-ed, as Lucene does by default, and hits are ordered by score. Each hit carries a snippet
of at most SNIPPET_CHARS characters around the first query word, never the whole section.
Queries longer than MAX_QUERY_CHARS are an error (Lucene caps the number of terms, and the
result echoes the query).
"""

import re

from neo4j import Driver, RoutingControl

from memex.query.models import DocHit, DocSearch
from memex.query.symbols import check_limit

SNIPPET_CHARS = 200
MAX_QUERY_CHARS = 500
_ELLIPSIS = "..."
_LUCENE_SPECIAL = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')
_OPERATOR = re.compile(r"\b(AND|OR|NOT)\b")
_TERM = re.compile(r"\w+")

_SEARCH = (
    "CALL db.index.fulltext.queryNodes('doc_text', $query) YIELD node, score "
    "WHERE node.codebase = $codebase "
    "WITH node, score ORDER BY score DESC, node.path, node.start_line LIMIT $fetch "
    "OPTIONAL MATCH (node)-[:MENTIONS]->(m) "
    "RETURN properties(node) AS props, score, collect(m.qualname) AS mentions "
    "ORDER BY score DESC, props.path, props.start_line"
)


def search_docs(driver: Driver, codebase: str, query: str, limit: int = 5) -> DocSearch:
    """Doc sections matching `query` in their heading path or text, best first."""
    text = query.strip()
    if not text:
        raise ValueError("query must not be empty")
    if len(text) > MAX_QUERY_CHARS:
        raise ValueError(f"query must be at most {MAX_QUERY_CHARS} characters, got {len(text)}")
    check_limit(limit)
    result = DocSearch(codebase=codebase, query=query, hits=[])
    if not _TERM.search(text):  # only punctuation: nothing to search for
        return result
    rows, _, _ = driver.execute_query(
        _SEARCH,
        query=escape_query(text),
        codebase=codebase,
        fetch=limit + 1,
        routing_=RoutingControl.READ,
    )
    hits = [
        DocHit(
            path=row["props"]["path"],
            heading_path=row["props"]["heading_path"],
            kind=row["props"].get("kind", "doc"),
            start_line=row["props"]["start_line"],
            end_line=row["props"]["end_line"],
            snippet=snippet(row["props"]["text"], text),
            mentions=sorted(row["mentions"]),
            score=row["score"],
        )
        for row in rows
    ]
    return result.model_copy(update={"hits": hits[:limit], "truncated": len(hits) > limit})


def escape_query(text: str) -> str:
    """`text` as a Lucene query that matches its words and nothing else."""
    escaped = _LUCENE_SPECIAL.sub(r"\\\1", text)
    return _OPERATOR.sub(lambda match: match.group().lower(), escaped)


def snippet(text: str, query: str) -> str:
    """At most SNIPPET_CHARS characters of `text` (whitespace collapsed) around the first
    whole-word occurrence of any query word, ignoring case, cut between words; `...` marks a
    cut. With no query word in the text, the snippet starts at its beginning."""
    flat = " ".join(text.split())
    if len(flat) <= SNIPPET_CHARS:
        return flat
    matches = [
        re.search(rf"\b{re.escape(term)}\b", flat, re.IGNORECASE) for term in _TERM.findall(query)
    ]
    found = [match.start() for match in matches if match]
    budget = SNIPPET_CHARS - 2 * len(_ELLIPSIS)

    start = max(0, min(found, default=0) - budget // 3)
    end = min(len(flat), start + budget)
    start = max(0, end - budget)
    if start > 0 and flat[start - 1] != " " and " " in flat[start:end]:
        start = flat.index(" ", start) + 1  # forward to the start of a word
    if end < len(flat) and flat[end] != " " and " " in flat[start:end]:
        end = flat.rindex(" ", start, end)  # back to the end of a word

    prefix = _ELLIPSIS if start > 0 else ""
    suffix = _ELLIPSIS if end < len(flat) else ""
    return prefix + flat[start:end].strip() + suffix
