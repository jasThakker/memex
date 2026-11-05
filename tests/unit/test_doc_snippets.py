"""The pure helpers behind search_docs: query escaping and snippets (DESIGN.md section 10)."""

import re

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
