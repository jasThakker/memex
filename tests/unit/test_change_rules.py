"""The text rules behind check_change (DESIGN.md section 10): code-shaped tokens in a
proposal, sentences of a doc section with their line ranges, and modal-verb stance."""

from pathlib import Path

import pytest

from memex.query.rules import Sentence, code_tokens, sentences, stance

DOCS = Path(__file__).resolve().parents[1] / "fixtures" / "docs"


def test_code_tokens_are_backtick_spans_dotted_snake_and_camel_names_in_order() -> None:
    description = (
        "Rename `base_url` on `AIProvider` and update OrderService.create, user_id handling, "
        "e.g. in app.routes.users.api; also call `get_one()` and BaseService. "
        "Do not touch I/O or HTTPClient, and `base_url` again."
    )
    assert code_tokens(description) == [
        "base_url",
        "AIProvider",
        "OrderService.create",
        "user_id",
        "app.routes.users.api",
        "get_one",
        "BaseService",
        "HTTPClient",
    ]


@pytest.mark.parametrize(
    "description",
    [
        "Make the services faster and simpler.",  # plain words, capitalized or not
        "Use i.e. and e.g. freely. OK?",  # abbreviations are not dotted names
        "Run `uv run pytest` and edit `app/routes/`.",  # spans that are not identifiers
    ],
)
def test_plain_text_has_no_code_tokens(description: str) -> None:
    assert code_tokens(description) == []


def test_a_section_body_is_split_into_sentences_with_their_lines() -> None:
    text = (DOCS / "rules.md").read_text(encoding="utf-8").rstrip("\n")
    assert sentences(text, first_line=1) == [
        Sentence("Never edit generated files by hand.", 1, 1),
        Sentence("Run the generator instead.", 1, 1),
        # e.g. does not end a sentence; a sentence runs across lines
        Sentence(
            "Services should call repositories, e.g. OrderRepository.get_one, and "
            "must not open sessions.",
            2,
            3,
        ),
        Sentence("You don't need to close them.", 3, 3),
        # each list item starts a new sentence; its marker is dropped
        Sentence("Always use `uv` for commands", 5, 5),
        Sentence("Avoid global state; prefer composables.", 6, 6),
        Sentence("This continues the list item.", 7, 7),
        # fenced code is skipped; each table row is its own sentence, separators are not
        Sentence("| Rule | Note |", 13, 13),
        Sentence("| Do not edit locales | Managed elsewhere |", 15, 15),
        Sentence("Run the tests!", 16, 16),
        Sentence("Then commit?", 16, 16),
        Sentence("Yes.", 16, 16),
    ]


def test_sentence_lines_are_offset_by_the_first_line() -> None:
    assert sentences("One.\n\nTwo.", first_line=40) == [
        Sentence("One.", 40, 40),
        Sentence("Two.", 42, 42),
    ]


def test_a_sentence_may_start_with_a_code_span() -> None:
    assert sentences("Keep routes thin. `get_order` must not touch the database.", 1) == [
        Sentence("Keep routes thin.", 1, 1),
        Sentence("`get_order` must not touch the database.", 1, 1),
    ]


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        ("Never edit generated files by hand.", "forbids"),
        ("Types are generated (**DO NOT EDIT MANUALLY**).", "forbids"),
        ("Other locales must never be modified.", "forbids"),
        ("Services must not open sessions.", "forbids"),
        ("You should not import routes here.", "forbids"),
        ("You shouldn't import routes here.", "forbids"),
        ("Don't call repos from routes.", "forbids"),
        ("Avoid global state.", "forbids"),
        ("Services should call repositories and must not open sessions.", "forbids"),
        ("All code must pass type checking.", "encourages"),
        ("Tests should cover new code.", "encourages"),
        ("Always use `uv` for Python commands.", "encourages"),
        ("Prefer composables over global state.", "encourages"),
        ("You don't need to close them.", "related"),
        ("You do not need to restart.", "related"),
        ("There is no need to run migrations.", "related"),
        ("A restart is not required.", "related"),
        ("Docs are not necessary for fixes.", "related"),
        ("Nevertheless, it shoulders the load.", "related"),  # whole words only
        ("Services read data through repositories.", "related"),
    ],
)
def test_stance_comes_from_modal_verbs(sentence: str, expected: str) -> None:
    assert stance(sentence) == expected
