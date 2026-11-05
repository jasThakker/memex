"""Smoke tests on Mealie, the primary benchmark (rules and an extractor). DESIGN.md section 12.

Needs `uv run python scripts/fetch_codebases.py`. Run with `uv run pytest -m realrepo`.
"""

from pathlib import Path

import pytest
import yaml

from memex.config import load_config
from memex.graph.model import ClassNode, DocNode, GraphBatch, ModuleNode
from memex.ingest import index_codebase

pytestmark = pytest.mark.realrepo

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def batch() -> GraphBatch:
    codebase = load_config(REPO_ROOT / "memex.toml").get("mealie")
    assert codebase.root.is_dir(), "run `uv run python scripts/fetch_codebases.py` first"
    return index_codebase(codebase)


def test_parses_with_zero_errors(batch: GraphBatch) -> None:
    assert batch.stats.parse_errors == ()
    assert batch.stats.files > 300


def test_no_duplicate_ids_and_no_dangling_edges(batch: GraphBatch) -> None:
    ids = [node.id for node in batch.nodes]
    dangling = [edge for edge in batch.edges if {edge.source, edge.target} - set(ids)]

    assert len(ids) == len(set(ids))
    assert dangling == []


def test_recipe_model_is_a_db_model_in_the_recipe_domain(batch: GraphBatch) -> None:
    [recipe] = [
        node for node in batch.nodes if isinstance(node, ClassNode) and node.name == "RecipeModel"
    ]

    assert recipe.qualname == "mealie.db.models.recipe.recipe.RecipeModel"
    assert (recipe.layer, recipe.domain) == ("db_models", "recipe")


def test_household_routes_are_in_the_household_domain(batch: GraphBatch) -> None:
    modules = [
        node
        for node in batch.nodes
        if isinstance(node, ModuleNode) and node.path.startswith("mealie/routes/households/")
    ]

    assert len(modules) > 5
    assert {(node.layer, node.domain) for node in modules} == {("routes", "household")}


def test_excluded_alembic_migrations_are_not_indexed(batch: GraphBatch) -> None:
    paths = [node.path for node in batch.nodes if isinstance(node, ModuleNode)]

    assert not [path for path in paths if path.startswith("mealie/alembic/")]


def test_recipe_model_has_incoming_references_from_other_models(batch: GraphBatch) -> None:
    classes = {node.id: node for node in batch.nodes if isinstance(node, ClassNode)}
    [recipe] = [node for node in classes.values() if node.name == "RecipeModel"]
    incoming = [
        edge for edge in batch.edges if edge.kind == "REFERENCES" and edge.target == recipe.id
    ]
    found = {(classes[edge.source].name, edge.ref_kind, edge.attr) for edge in incoming}

    assert recipe.tablename == "recipes"
    # Both ForeignKey("recipes.id") columns of mealie/db/models/recipe/ingredient.py.
    assert ("RecipeIngredientModel", "foreign_key", "recipe_id") in found
    assert ("RecipeIngredientModel", "foreign_key", "referenced_recipe_id") in found
    assert len(incoming) >= 20
    assert {classes[edge.source].layer for edge in incoming} == {"db_models"}
    assert {edge.extractor for edge in incoming} == {"sqlalchemy"}


def docs_of(batch: GraphBatch) -> list[DocNode]:
    return [node for node in batch.nodes if isinstance(node, DocNode)]


def mentioned_by(batch: GraphBatch, doc_id: str) -> set[str]:
    return {e.target for e in batch.edges if e.kind == "MENTIONS" and e.source == doc_id}


def test_agents_md_generated_types_rule_is_a_doc_that_mentions_resolved_symbols(
    batch: GraphBatch,
) -> None:
    # AGENTS.md: "TypeScript types auto-generated from Pydantic schemas - **never manually
    # edit** `frontend/app/lib/api/types/`", under "### Backend Architecture (mealie/)".
    [rule] = [doc for doc in docs_of(batch) if "**never manually edit**" in doc.text]

    assert rule.id == "mealie:doc:AGENTS.md#Backend Architecture (mealie/)"
    assert rule.heading_path == (
        "Mealie Development Guide for AI Agents > Architecture & Key Patterns > "
        "Backend Architecture (mealie/)"
    )
    assert rule.kind == "agents"
    assert {
        "mealie:mealie.repos.repository_factory.AllRepositories",
        "mealie:mealie.services._base_service.BaseService",
        "mealie:mealie.db.db_setup.session_context",
        "mealie:mealie.routes._base.mixins",
    } <= mentioned_by(batch, rule.id)


def test_doc_kinds_come_from_the_config(batch: GraphBatch) -> None:
    kinds = {doc.path: doc.kind for doc in docs_of(batch)}

    assert kinds["AGENTS.md"] == "agents"
    assert kinds["docs/docs/contributors/developers-guide/database-changes.md"] == "contributor"
    assert set(kinds.values()) == {"agents", "contributor", "user"}


def test_every_doc_cited_by_the_eval_is_a_doc_node(batch: GraphBatch) -> None:
    questions = yaml.safe_load((REPO_ROOT / "eval" / "questions.yaml").read_text())
    cited = {ref for q in questions for ref in q["expected"].get("docs", [])}
    ids = {doc.id for doc in docs_of(batch)}

    assert len(cited) > 5
    assert sorted(ref for ref in cited if f"mealie:doc:{ref}" not in ids) == []
