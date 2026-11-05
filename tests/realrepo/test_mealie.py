"""Smoke tests on Mealie, the primary benchmark (rules and an extractor). DESIGN.md section 12.

Needs `uv run python scripts/fetch_codebases.py`. Run with `uv run pytest -m realrepo`.
"""

from pathlib import Path

import pytest

from memex.config import load_config
from memex.graph.model import ClassNode, GraphBatch, ModuleNode
from memex.ingest.code import index_code

pytestmark = pytest.mark.realrepo

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def batch() -> GraphBatch:
    codebase = load_config(REPO_ROOT / "memex.toml").get("mealie")
    assert codebase.root.is_dir(), "run `uv run python scripts/fetch_codebases.py` first"
    return index_code(codebase)


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
