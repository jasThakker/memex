"""The tool contract (DESIGN.md section 10): Pydantic models every MCP tool returns.

Frozen after Phase 3 with ADR-001: the field sets asserted here are the contract, so a change
to them needs an ADR. Results hold locations, signatures and first docstring lines, never
source bodies. Every result that holds a list carries `truncated`.
"""

import json
import os
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from memex.query import models as m

# Each model's exact fields. This table is what ADR-001 freezes.
CONTRACT: dict[type[BaseModel], set[str]] = {
    # shared pieces
    m.SymbolRef: {"qualname", "kind", "path", "line", "layer", "domain"},
    m.Symbol: {"qualname", "kind", "path", "line", "layer", "domain", "signature", "docstring"},
    m.Citation: {"path", "heading_path", "start_line", "end_line"},
    m.DocRef: {"path", "heading_path", "start_line", "end_line", "mentions"},
    # list_codebases
    m.CodebaseInfo: {
        "name",
        "source",
        "ref",
        "commit",
        "indexed_at",
        "files",
        "extractors",
        "parse_errors",
        "unresolved_calls",
        "nodes",
        "edges",
    },
    m.CodebaseList: {"codebases", "truncated"},
    # memex stats (CLI): the list_codebases entry plus label distributions
    m.CodebaseStats: {
        "name",
        "source",
        "ref",
        "commit",
        "indexed_at",
        "files",
        "extractors",
        "parse_errors",
        "unresolved_calls",
        "nodes",
        "edges",
        "layers",
        "domains",
    },
    # find_symbol
    m.SymbolSearch: {"codebase", "query", "kind", "symbols", "truncated"},
    # callers, callees
    m.CallHop: {"function", "via", "line", "confidence", "distance"},
    m.CallGraph: {
        "codebase",
        "symbol",
        "candidates",
        "direction",
        "depth",
        "calls",
        "truncated",
    },
    # impact_of
    m.PathStep: {"edge", "to"},
    m.Dependent: {"symbol", "distance", "path"},
    m.LayerGroup: {"layer", "dependents"},
    m.Impact: {
        "codebase",
        "symbol",
        "candidates",
        "max_depth",
        "total",
        "layers",
        "docs",
        "truncated",
    },
    # search_docs
    m.DocHit: {
        "path",
        "heading_path",
        "kind",
        "start_line",
        "end_line",
        "snippet",
        "mentions",
        "score",
    },
    m.DocSearch: {"codebase", "query", "hits", "truncated"},
    # module_summary (stretch; in the contract now so it needs no ADR later)
    m.ClassSummary: {"name", "line", "bases", "methods"},
    m.FunctionSummary: {"name", "line", "signature"},
    m.ModuleSummary: {
        "codebase",
        "module",
        "candidates",
        "docstring",
        "classes",
        "functions",
        "imports",
        "imported_by",
        "docs",
        "truncated",
    },
}

TOOL_RESULTS = [
    m.CodebaseList,
    m.SymbolSearch,
    m.CallGraph,
    m.Impact,
    m.DocSearch,
    m.ModuleSummary,
]

RECIPE = m.SymbolRef(
    qualname="app.db.models.recipe.RecipeModel",
    kind="class",
    path="app/db/models/recipe.py",
    line=12,
    layer="db_models",
    domain="recipe",
)
SERVICE = m.SymbolRef(
    qualname="app.services.recipe_service.RecipeService.create",
    kind="function",
    path="app/services/recipe_service.py",
    line=40,
    layer="services",
    domain="recipe",
)


def test_every_model_has_exactly_the_contract_fields() -> None:
    mismatched = {
        model.__name__: sorted(set(model.model_fields) ^ fields)
        for model, fields in CONTRACT.items()
        if set(model.model_fields) != fields
    }
    assert mismatched == {}


def test_the_contract_lists_every_model_in_the_module() -> None:
    defined = {
        value
        for value in vars(m).values()
        if isinstance(value, type)
        and issubclass(value, BaseModel)
        and value.__module__ == m.__name__
    }
    assert defined - {m.Contract} == set(CONTRACT)


def test_every_tool_result_carries_truncated_defaulting_to_false() -> None:
    for model in TOOL_RESULTS:
        assert model.model_fields["truncated"].default is False, model.__name__


def test_models_are_frozen_and_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        RECIPE.line = 13  # type: ignore[misc]
    with pytest.raises(ValidationError):
        m.SymbolRef.model_validate({**RECIPE.model_dump(), "body": "class RecipeModel: ..."})


def test_literal_fields_reject_values_outside_the_contract() -> None:
    with pytest.raises(ValidationError):
        m.SymbolRef.model_validate({**RECIPE.model_dump(), "kind": "variable"})
    with pytest.raises(ValidationError):
        m.CallHop(function=SERVICE, via="x", line=1, confidence="maybe", distance=1)
    with pytest.raises(ValidationError):
        m.PathStep(edge="DEFINES", to="x")  # impact follows CALLS, INHERITS, REFERENCES, IMPORTS


EXAMPLES: list[BaseModel] = [
    m.CodebaseList(
        codebases=[
            m.CodebaseInfo(
                name="shop",
                source="https://example.com/shop",
                ref="v1",
                commit="0" * 40,
                indexed_at="2026-11-05T10:00:00+00:00",
                files=27,
                extractors=["sqlalchemy"],
                parse_errors=0,
                unresolved_calls=5,
                nodes={"Module": 27, "Class": 14},
                edges={"CALLS": 14, "REFERENCES": 3},
            )
        ]
    ),
    m.SymbolSearch(
        codebase="shop",
        query="RecipeModel",
        kind="any",
        symbols=[m.Symbol(**RECIPE.model_dump(), docstring="A recipe row.")],
    ),
    m.CallGraph(
        codebase="shop",
        symbol=SERVICE,
        direction="callers",
        depth=2,
        calls=[
            m.CallHop(function=RECIPE, via=SERVICE.qualname, line=7, confidence="exact", distance=1)
        ],
        truncated=True,
    ),
    m.CallGraph(  # an ambiguous short name: no symbol, the candidates instead
        codebase="shop",
        symbol=None,
        candidates=[RECIPE, SERVICE],
        direction="callees",
        depth=1,
    ),
    m.Impact(
        codebase="shop",
        symbol=RECIPE,
        max_depth=3,
        total=1,
        layers=[
            m.LayerGroup(
                layer="services",
                dependents=[
                    m.Dependent(
                        symbol=SERVICE,
                        distance=2,
                        path=[
                            m.PathStep(edge="CALLS", to="app.repos.recipes.RecipeRepo.get"),
                            m.PathStep(edge="IMPORTS", to=RECIPE.qualname),
                        ],
                    )
                ],
            )
        ],
        docs=[
            m.DocRef(
                path="docs/db.md",
                heading_path="Database",
                start_line=1,
                end_line=9,
                mentions=[RECIPE.qualname],
            )
        ],
    ),
    m.DocSearch(
        codebase="shop",
        query="generated types",
        hits=[
            m.DocHit(
                path="AGENTS.md",
                heading_path="Rules > Generated code",
                kind="agents",
                start_line=10,
                end_line=14,
                snippet="Never edit generated types by hand.",
                mentions=[],
                score=2.5,
            )
        ],
    ),
    m.ModuleSummary(
        codebase="shop",
        module=RECIPE.model_copy(update={"kind": "module", "line": None}),
        docstring="Recipe table.",
        classes=[m.ClassSummary(name="RecipeModel", line=12, bases=["Base"], methods=["save"])],
        functions=[m.FunctionSummary(name="helper", line=40, signature="helper() -> None")],
        imports=["app.db.models.base"],
        imported_by=3,
    ),
]


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda example: type(example).__name__)
def test_examples_round_trip_through_json(example: BaseModel) -> None:
    assert type(example).model_validate_json(example.model_dump_json()) == example


SCHEMA_SNAPSHOT = Path(__file__).with_name("contract_schema.json")


def _shape(schema: object) -> object:
    """A JSON schema without docstrings and titles: rewording a docstring is not a change."""
    if isinstance(schema, dict):
        return {k: _shape(v) for k, v in schema.items() if k not in ("description", "title")}
    if isinstance(schema, list):
        return [_shape(item) for item in schema]
    return schema


def test_contract_types_match_the_committed_snapshot() -> None:
    """Field types, required fields and defaults are frozen too, not only names (ADR-001).

    After an ADR-approved change, regenerate with MEMEX_UPDATE_CONTRACT=1 and review the diff.
    """
    schemas = {model.__name__: _shape(model.model_json_schema()) for model in CONTRACT}
    if os.environ.get("MEMEX_UPDATE_CONTRACT") == "1":
        SCHEMA_SNAPSHOT.write_text(json.dumps(schemas, indent=2, sort_keys=True) + "\n")
    assert schemas == json.loads(SCHEMA_SNAPSHOT.read_text())
