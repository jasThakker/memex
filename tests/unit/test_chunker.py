from pathlib import Path

import pytest

from memex.ingest.docs.chunker import Chunk, chunk, plain_heading

DOCS = Path(__file__).resolve().parents[1] / "fixtures" / "docs"


def test_guide_is_split_at_every_real_heading() -> None:
    chunks = chunk((DOCS / "guide.md").read_text(encoding="utf-8"))
    assert chunks == [
        Chunk(  # text before the first heading; front matter is not part of it
            anchor="",
            heading_path="",
            text="Intro text before any heading.",
            start_line=6,
            end_line=6,
        ),
        Chunk(
            anchor="Team Guide",
            heading_path="Team Guide",
            text="Read this first.",
            start_line=8,
            end_line=10,
        ),
        Chunk(  # a `#` line inside a fence is not a heading
            anchor="Setup",
            heading_path="Team Guide > Setup",
            text="```bash\n# install deps, not a heading\nmake setup\n```",
            start_line=12,
            end_line=17,
        ),
        Chunk(
            anchor="Client and Server",
            heading_path="Team Guide > Setup > Client and Server",
            text="Details.",
            start_line=19,
            end_line=21,
        ),
        Chunk(  # a repeated heading in the same file gets a counter in its anchor only
            anchor="Setup (2)",
            heading_path="Team Guide > Setup",
            text="Second setup section.",
            start_line=23,
            end_line=25,
        ),
        Chunk(  # setext level 2; a `---` after a blank line is a rule, not a heading
            anchor="Usage Notes",
            heading_path="Team Guide > Usage Notes",
            text="Setext level 2.\n\n---\n\nAfter a rule, still under Usage Notes.",
            start_line=27,
            end_line=34,
        ),
        Chunk(  # setext level 1 starts a new top-level path
            anchor="Appendix",
            heading_path="Appendix",
            text=(
                "~~~\n## fenced with tildes\n~~~\n\n"
                "    # indented code, not a heading\n\n#hashtag is not a heading"
            ),
            start_line=36,
            end_line=45,
        ),
        Chunk(anchor="Empty", heading_path="Appendix > Empty", text="", start_line=47, end_line=47),
    ]


def test_file_without_headings_is_one_preamble_chunk() -> None:
    assert chunk("\nJust text.\nMore text.\n\n") == [
        Chunk(anchor="", heading_path="", text="Just text.\nMore text.", start_line=2, end_line=3)
    ]


def test_blank_file_and_blank_preamble_give_no_preamble_chunk() -> None:
    assert chunk("") == []
    assert chunk("\n\n# Title\n") == [
        Chunk(anchor="Title", heading_path="Title", text="", start_line=3, end_line=3)
    ]


def test_windows_line_endings_and_indented_atx_heading() -> None:
    assert chunk("   ## Up to three spaces\r\nbody\r\n") == [
        Chunk(
            anchor="Up to three spaces",
            heading_path="Up to three spaces",
            text="body",
            start_line=1,
            end_line=2,
        )
    ]


def test_a_skipped_level_still_nests_under_the_nearest_higher_heading() -> None:
    chunks = chunk("# A\n### C\n## B\n#### D\n")
    assert [c.heading_path for c in chunks] == ["A", "A > C", "A > B", "A > B > D"]


def test_repeated_anchor_skips_a_counter_that_is_already_a_heading() -> None:
    chunks = chunk("# X\n# X (2)\n# X\n")
    assert [c.anchor for c in chunks] == ["X", "X (2)", "X (3)"]


@pytest.mark.parametrize(
    ("raw", "plain"),
    [
        ("Title #", "Title"),  # closing sequence
        ("Title ###   ", "Title"),
        ("C#", "C#"),  # not a closing sequence: no space before it
        ("Report bugs via [issues](https://example.com/issues)", "Report bugs via issues"),
        ("See [the docs][ref] now", "See the docs now"),
        ("![logo](logo.png) Title", "logo Title"),
        ("`session_context` and _private_ use", "session_context and private use"),
        ("**Bold**  and   *it* and __this__", "Bold and it and this"),
        ("snake_case_name stays", "snake_case_name stays"),
        ("`/a/b` → `/a/c` (:octicons-tag-24: v3.23.0)", "/a/b → /a/c (:octicons-tag-24: v3.23.0)"),
        ("`**not emphasis**`", "**not emphasis**"),  # code span content is literal
        ("Backend Architecture (pkg/)", "Backend Architecture (pkg/)"),
    ],
)
def test_plain_heading(raw: str, plain: str) -> None:
    assert plain_heading(raw) == plain


@pytest.mark.parametrize(
    "text",
    [
        "- first item\n  wraps here\n---\n",  # a wrapped list item, then a rule
        "> quote\nlazy line\n---\n",  # a lazy quote continuation, then a rule
        "- item\n---\n",
        "> q\n---\n",
        "| a | b |\n---\n",
        '<div align="center">\n<img src=x>\n</div>\n---\n',  # HTML, then a rule
        "<!--\n## Old section\nstale text\n-->\n",  # commented out
        "para\n***\n",  # a thematic break ends the paragraph; `***` is never setext
        "```\n    ```\n# Not a heading\n```\n",  # 4 spaces: not a closing fence
        "````\n```\n# x\n````\n",  # a shorter fence does not close a longer one
        "para\n    # x\n",  # paragraph continuation, not indented code or a heading
    ],
)
def test_not_a_heading(text: str) -> None:
    assert [c.anchor for c in chunk(text)] == [""]


def test_an_unclosed_front_matter_is_ordinary_text() -> None:
    assert [c.anchor for c in chunk("---\ntitle: x\n# Real\n")] == ["", "Real"]


def test_a_backtick_line_with_a_backtick_in_its_info_string_is_not_a_fence() -> None:
    assert [c.anchor for c in chunk("```pip install foo```\n\n## Next\n")] == ["", "Next"]


def test_headings_after_an_html_comment_are_found() -> None:
    assert [c.anchor for c in chunk("<!--\nnote\nend -->\n# After\n")] == ["", "After"]


def test_a_setext_heading_takes_its_whole_paragraph() -> None:
    assert chunk("Intro line one\nline two\n---\nbody\n") == [
        Chunk(
            anchor="Intro line one line two",
            heading_path="Intro line one line two",
            text="body",
            start_line=1,
            end_line=4,
        )
    ]


@pytest.mark.parametrize("separator", ["\x0c", "\x0b", "\x85", " "])
def test_only_newlines_end_a_line(separator: str) -> None:
    chunks = chunk(f"a{separator}b\n# H\n")
    assert [(c.anchor, c.start_line) for c in chunks] == [("", 1), ("H", 2)]
    assert chunks[0].text == f"a{separator}b"


@pytest.mark.parametrize(
    ("raw", "plain"),
    [
        ('Installation <a name="install"></a>', "Installation"),
        ("Line <br/> break", "Line break"),
        ("`Map<K, V>` types", "Map<K, V> types"),  # code span content is literal
        ("Use [Config] here", "Use Config here"),  # shortcut reference link
    ],
)
def test_plain_heading_drops_inline_html_and_shortcut_links(raw: str, plain: str) -> None:
    assert plain_heading(raw) == plain


@pytest.mark.parametrize("text", ["para\n***\nnext\n---\n", "para\n\n---\nnext\n===\n"])
def test_a_thematic_break_ends_the_paragraph_before_a_setext_heading(text: str) -> None:
    assert [c.anchor for c in chunk(text)] == ["", "next"]


@pytest.mark.parametrize(
    "text",
    [
        "Requirements:\n- Python\n- Docker\n---\n",  # a list interrupts the paragraph
        "Note:\n> quoted\n---\n",  # so does a quote
        "Intro\n<div>\nx\n</div>\n---\n",  # and an HTML block
        "Para\n- item\nlazy\n---\n",  # a lazy line after the list item changes nothing
    ],
)
def test_a_paragraph_interrupted_by_a_list_quote_or_html_is_never_a_heading(text: str) -> None:
    assert [c.anchor for c in chunk(text)] == [""]


def test_a_heading_after_an_interrupted_paragraph_is_not_nested_under_it() -> None:
    chunks = chunk("Requirements:\n- Python\n- Docker\n---\n## Next\n")
    assert [(c.anchor, c.heading_path) for c in chunks] == [("", ""), ("Next", "Next")]


@pytest.mark.parametrize("comment", ["<!-->", "<!--->", "<!---->"])
def test_a_comment_that_closes_on_its_opener_line_is_closed(comment: str) -> None:
    assert [c.anchor for c in chunk(f"{comment}\n# A\n")] == ["", "A"]
