"""The pure helpers behind search_docs: query escaping and snippets (DESIGN.md section 10)."""

import re

import pytest

from memex.query.docs import SNIPPET_CHARS, escape_query, snippet

LONG = (
    " ".join(f"word{i}" for i in range(200))
    + " the needle sits here "
    + " ".join(f"tail{i}" for i in range(200))
)


def test_lucene_special_characters_are_escaped() -> None:
    assert escape_query('a+b (c) "d" e* f? g:h') == r"a\+b \(c\) \"d\" e\* f\? g\:h"
    assert escape_query(r"x\y/z") == r"x\\y\/z"
    assert escape_query("[a] {b} ~c ^d !e") == r"\[a\] \{b\} \~c \^d \!e"
    assert escape_query("a && b || c - d") == r"a \&\& b \|\| c \- d"


def test_boolean_operator_words_lose_their_meaning() -> None:
    # Lucene reads upper-case AND, OR and NOT as operators; the analyzer lower-cases anyway.
    assert escape_query("never AND always OR NOT this") == "never and always or not this"
    assert escape_query("ANDROID NOTE") == "ANDROID NOTE"


def test_a_short_text_is_returned_whole_with_whitespace_collapsed() -> None:
    assert snippet("Never edit\n\n  the generated types.", "generated") == (
        "Never edit the generated types."
    )


def test_a_long_text_is_cut_around_the_first_matching_term() -> None:
    result = snippet(LONG, "needle")

    assert "needle" in result
    assert len(result) <= SNIPPET_CHARS
    assert result.startswith("...") and result.endswith("...")


def test_cuts_fall_on_word_boundaries() -> None:
    words = set(LONG.split())
    result = snippet(LONG, "needle")

    assert set(result.strip(".").split()) <= words


def test_matching_ignores_case_and_uses_any_term() -> None:
    assert "needle" in snippet(LONG, "missing NEEDLE")


def test_with_no_matching_term_the_text_starts_the_snippet() -> None:
    result = snippet(LONG, "absent")

    assert result.startswith("word0 word1")
    assert result.endswith("...")
    assert len(result) <= SNIPPET_CHARS


def test_query_punctuation_does_not_break_matching() -> None:
    result = snippet(LONG, "(needle)!")

    assert "needle" in result
    assert not re.search(r"\s{2,}", result)


def test_terms_match_whole_words_only() -> None:
    # "orm" is inside "Information" at the start; the real hit is the word ORM much later.
    text = "Information about the models. " + "filler " * 40 + "The ORM layer maps tables."

    assert "ORM" in snippet(text, "orm")


@pytest.mark.parametrize("width", range(3, 10))
def test_no_word_that_fits_is_dropped_at_a_cut(width: int) -> None:
    # The kept words plus one neighbour on each side must not fit in the window: if they did,
    # a word that fitted was dropped. Different word widths put the cuts on spaces or inside
    # words.
    words = [f"w{i:0{width - 1}d}" for i in range(300)]
    budget = SNIPPET_CHARS - 2 * len("...")
    for position in range(60, 80):
        kept = snippet(" ".join(words), words[position]).strip(".").split()
        first, last = words.index(kept[0]), words.index(kept[-1])

        assert words[position] in kept
        assert len(" ".join(words[first - 1 : last + 2])) > budget, (width, position)


def test_a_query_term_at_the_very_start_keeps_the_start() -> None:
    assert snippet(LONG, "word0").startswith("word0 ")
