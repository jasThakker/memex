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
