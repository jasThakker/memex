"""check_change (DESIGN.md section 10): which code a proposed change affects and which
documented rules apply.

Affected counts are worked out from the impact_of expectations in test_query_impact.py
(BaseService has 12 dependents within depth 3; app.repos.repository_users has 2 others).
Needs Docker. Run with `uv run pytest -m neo4j`.
"""

from dataclasses import replace
from pathlib import Path

import pytest
from neo4j import Driver

from memex.config import load_config
from memex.graph.model import DocNode, Edge, GraphBatch, code_id, doc_id
from memex.graph.store import ensure_schema, replace_codebase
from memex.ingest import index_codebase
from memex.ingest.code import index_code
from memex.query import change
from memex.query.change import check_change
from memex.query.models import ChangeCheck, ChangeProposal, Citation, Guideline, LayerCount

pytestmark = pytest.mark.neo4j

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REGISTRY = load_config(FIXTURES / "memex.toml")
LAYERED = index_code(REGISTRY.get("layered_app"))

BASE = "app._base.service.BaseService"
USER_REPOS = "app.repos.repository_users"

BASE_AFFECTED = [
    LayerCount(layer="base", count=1),
    LayerCount(layer="routes", count=4),
    LayerCount(layer="services", count=7),
]


@pytest.fixture
def indexed(driver: Driver) -> Driver:
    ensure_schema(driver)
    replace_codebase(driver, LAYERED)
    return driver


def check(driver: Driver, description: str, symbols: list[str] | None = None) -> ChangeCheck:
    proposal = ChangeProposal(description=description, symbols=symbols or [])
    return check_change(driver, "layered_app", proposal)


def resolved(result: ChangeCheck) -> list[str]:
    return [ref.qualname for ref in result.resolved_symbols]


def test_explicit_symbols_are_resolved_and_their_dependents_counted_by_layer(
    indexed: Driver,
) -> None:
    result = check(indexed, "Rename the base class.", ["BaseService"])

    assert result.codebase == "layered_app"
    assert resolved(result) == [BASE]
    assert result.ambiguous == []
    assert result.unresolved == []
    assert result.affected.total == 12
    assert result.affected.layers == BASE_AFFECTED
    assert result.truncated is False


def test_explicit_symbols_win_over_names_in_the_description(indexed: Driver) -> None:
    result = check(indexed, "Change `BaseService` too.", ["UserRepository"])

    assert resolved(result) == [f"{USER_REPOS}.UserRepository"]


def test_without_symbols_code_names_in_the_description_are_resolved(indexed: Driver) -> None:
    result = check(indexed, f"Change `BaseService` and split {USER_REPOS} in two.")

    assert resolved(result) == [BASE, USER_REPOS]
    # one walk from both start sets: repository_factory and OrderService.owner_name join
    assert result.affected.total == 14
    assert result.affected.layers == [
        LayerCount(layer="base", count=1),
        LayerCount(layer="repos", count=1),
        LayerCount(layer="routes", count=4),
        LayerCount(layer="services", count=8),
    ]


def test_a_symbol_named_twice_is_resolved_once(indexed: Driver) -> None:
    result = check(indexed, "Rename it.", ["BaseService", BASE])

    assert resolved(result) == [BASE]
    assert result.affected.total == 12


def test_a_shared_short_name_is_ambiguous_never_guessed(indexed: Driver) -> None:
    result = check(indexed, "Make `get_one` cache its rows.")

    assert result.resolved_symbols == []
    assert [a.name for a in result.ambiguous] == ["get_one"]
    assert [c.qualname for c in result.ambiguous[0].candidates] == [
        "app.repos.repository_orders.OrderRepository.get_one",
        f"{USER_REPOS}.UserRepository.get_one",
    ]
    assert result.affected.total == 0
    assert result.affected.layers == []


def test_names_that_match_nothing_are_unresolved(indexed: Driver) -> None:
    result = check(indexed, "Rename `base_url` and NoSuchThing; keep the rest.")

    assert result.resolved_symbols == []
    assert result.unresolved == ["base_url", "NoSuchThing"]
    assert result.affected.total == 0


def test_plain_words_are_neither_resolved_nor_unresolved(indexed: Driver) -> None:
    result = check(indexed, "Make the services faster.")

    assert result.resolved_symbols == []
    assert result.unresolved == []


def test_at_most_max_tokens_names_are_read_from_the_description(indexed: Driver) -> None:
    names = [f"name_{i}" for i in range(change.MAX_TOKENS + 2)]
    result = check(indexed, "Rename " + ", ".join(names) + ".")

    assert result.unresolved == names[: change.MAX_TOKENS]
    assert result.truncated is True


def test_candidates_of_an_ambiguous_name_are_capped(
    indexed: Driver, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(change, "MAX_CANDIDATES", 2)
    result = check(indexed, "Change `__init__` everywhere.")

    assert [c.qualname for c in result.ambiguous[0].candidates] == [
        "app._base.service.BaseService.__init__",
        "app.repos.repository_factory.AllRepositories.__init__",
    ]
    assert result.truncated is True


@pytest.mark.parametrize("description", ["", "   ", "x" * 501])
def test_the_description_must_be_plain_text_of_at_most_500_characters(
    indexed: Driver, description: str
) -> None:
    with pytest.raises(ValueError, match="description"):
        check(indexed, description, ["BaseService"])


# Guidelines from doc sections that MENTION the resolved symbols, their members or their
# dependents. (path, heading_path, start_line, body lines, qualnames it mentions); the body
# starts on the line after the heading.
DOCS = [
    (
        "docs/services.md",
        "Guide > Services",
        10,
        [
            "Services read data through repositories.",  # names no mentioned symbol
            "Every service must inherit from `BaseService`.",
            "Never construct",  # one sentence over two lines
            "`BaseService` directly; use a subclass.",
            "You may call `BaseService.__init__` from tests.",  # names the method, not the class
        ],
        [BASE],
    ),
    (
        "docs/scripts.md",
        "Scripts",
        1,
        ["You don't need to subclass `BaseService` in scripts."],  # negated: related
        [BASE],
    ),
    (
        "docs/heading.md",
        "Using BaseService",  # mentioned in the heading only
        1,
        ["Always pass the repositories in.", "It is simple."],
        [BASE],
    ),
    (
        "docs/init.md",
        "Init",
        1,
        ["Never call `BaseService.__init__` twice."],
        [f"{BASE}.__init__"],  # a member of the start set
    ),
    (
        "docs/routes.md",
        "Routes",
        1,
        ["Routes should stay thin.", "`get_order` must not touch the database."],
        ["app.routes.orders.api.get_order"],  # a dependent at distance 2
    ),
    (
        "docs/models.md",
        "Models",
        1,
        ["Never rename `Order` columns."],
        ["app.db.models.orders.Order"],  # unrelated to BaseService
    ),
    (
        "docs/locales.md",
        "Translations",
        1,
        [
            "Only edit the English locale files.",
            "Other locale files must never be modified by hand.",
            "Translators work in a separate tool.",  # shares no word with the proposal
        ],
        [],  # found by search only
    ),
]


def with_docs(docs: list[tuple[str, str, int, list[str], list[str]]] = DOCS) -> GraphBatch:
    nodes, edges = [], []
    for path, heading_path, start, body, mentioned in docs:
        node_id = doc_id("layered_app", path, heading_path)
        nodes.append(
            DocNode(
                id=node_id,
                codebase="layered_app",
                path=path,
                heading_path=heading_path,
                anchor=heading_path,
                text="\n".join(body),
                start_line=start,
                end_line=start + len(body),
            )
        )
        edges.extend(
            Edge(
                kind="MENTIONS", source=node_id, target=code_id("layered_app", q), match="qualname"
            )
            for q in mentioned
        )
    return replace(LAYERED, nodes=LAYERED.nodes + tuple(nodes), edges=LAYERED.edges + tuple(edges))


@pytest.fixture
def documented(driver: Driver) -> Driver:
    ensure_schema(driver)
    replace_codebase(driver, with_docs())
    return driver


def mentioned(
    stance: str, quote: str, path: str, heading_path: str, lines: tuple[int, int]
) -> Guideline:
    return Guideline(
        stance=stance,  # type: ignore[arg-type]
        quote=quote,
        citation=Citation(
            path=path, heading_path=heading_path, start_line=lines[0], end_line=lines[1]
        ),
        matched_on="mention",
    )


BASE_GUIDELINES = [
    # the symbol itself first (by path), then a member, then the closest dependent
    mentioned(
        "encourages",
        "Always pass the repositories in.",
        "docs/heading.md",
        "Using BaseService",
        (2, 2),
    ),
    mentioned(
        "related",
        "You don't need to subclass `BaseService` in scripts.",
        "docs/scripts.md",
        "Scripts",
        (2, 2),
    ),
    mentioned(
        "encourages",
        "Every service must inherit from `BaseService`.",
        "docs/services.md",
        "Guide > Services",
        (12, 12),
    ),
    mentioned(
        "forbids",
        "Never construct `BaseService` directly; use a subclass.",
        "docs/services.md",
        "Guide > Services",
        (13, 14),
    ),
    mentioned(
        "forbids", "Never call `BaseService.__init__` twice.", "docs/init.md", "Init", (2, 2)
    ),
    mentioned(
        "forbids", "`get_order` must not touch the database.", "docs/routes.md", "Routes", (3, 3)
    ),
]


def test_docs_mentioning_the_change_give_cited_sentences_with_a_stance(
    documented: Driver,
) -> None:
    result = check(documented, "Tidy it up.", ["BaseService"])

    assert result.guidelines == BASE_GUIDELINES
    assert result.truncated is False


def test_guidelines_are_capped_keeping_those_with_a_stance(
    documented: Driver, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(change, "MAX_GUIDELINES", 3)
    result = check(documented, "Tidy it up.", ["BaseService"])

    # the related scripts.md sentence gives way; the rest keep their order
    assert result.guidelines == [BASE_GUIDELINES[i] for i in (0, 2, 3)]
    assert result.truncated is True


def test_nothing_resolved_gives_no_mention_guidelines(documented: Driver) -> None:
    result = check(documented, "Tidy it up.", ["NoSuchThing"])

    assert [g for g in result.guidelines if g.matched_on == "mention"] == []


def searched(stance: str, quote: str, path: str, heading_path: str, line: int) -> Guideline:
    return mentioned(stance, quote, path, heading_path, (line, line)).model_copy(
        update={"matched_on": "search"}
    )


def test_a_full_text_search_on_the_description_finds_rules_no_symbol_names(
    documented: Driver,
) -> None:
    result = check(documented, "Add a German translation by editing the locale files.")

    assert result.resolved_symbols == []
    # sentences sharing a word of the proposal, a stance first; then in line order
    assert result.guidelines == [
        searched(
            "related", "Only edit the English locale files.", "docs/locales.md", "Translations", 2
        ),
        searched(
            "forbids",
            "Other locale files must never be modified by hand.",
            "docs/locales.md",
            "Translations",
            3,
        ),
    ]


def test_a_sentence_found_both_ways_is_listed_once_as_a_mention(
    documented: Driver, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(change, "MAX_GUIDELINES", 50)
    result = check(documented, "Construct `BaseService` directly in scripts.")

    cited = [(g.citation.path, g.citation.start_line) for g in result.guidelines]
    assert len(cited) == len(set(cited))
    construct = [g for g in result.guidelines if g.quote.startswith("Never construct")]
    assert [g.matched_on for g in construct] == ["mention"]
    # search alone finds it too, so the mention really won the merge
    alone = check(documented, "Construct `BaseService` directly in scripts.", ["NoSuchThing"])
    assert [g.matched_on for g in alone.guidelines if g.quote.startswith("Never construct")] == [
        "search"
    ]
    # every mention before every search hit
    kinds = [g.matched_on for g in result.guidelines]
    assert kinds == sorted(kinds)


def test_on_the_real_fixture_docs_a_rule_against_an_ambiguous_name_is_found_by_search(
    driver: Driver,
) -> None:
    ensure_schema(driver)
    replace_codebase(driver, index_codebase(REGISTRY.get("layered_app")))

    result = check(driver, "Call `get_one` on a repository from a route.")

    assert [a.name for a in result.ambiguous] == ["get_one"]
    layers = [g for g in result.guidelines if g.citation.heading_path == "Agent Guide > Layers"]
    assert layers == [
        searched(
            "forbids",
            "Routes in `app/routes/` call services, never repos directly.",
            "AGENTS.md",
            "Agent Guide > Layers",
            7,
        ),
        searched(
            "forbids",
            "Never call `get_one` on a repository from a route.",
            "AGENTS.md",
            "Agent Guide > Layers",
            9,
        ),
    ]


def test_on_the_real_fixture_docs_a_mention_cites_its_line(driver: Driver) -> None:
    ensure_schema(driver)
    replace_codebase(driver, index_codebase(REGISTRY.get("layered_app")))

    result = check(driver, "Tidy it up.", ["BaseService"])

    assert [g for g in result.guidelines if g.citation.path == "AGENTS.md"] == [
        mentioned(
            "related",
            "Services inherit from `BaseService` and get repositories from `AllRepositories`.",
            "AGENTS.md",
            "Agent Guide > Layers",
            (8, 8),
        )
    ]


# Reviewer run 1 cases, each in its own doc so the lists above stay as they are.
LONG = ", ".join(["the repositories are passed in by the caller"] * 5)  # one sentence
REVIEW_DOCS = [
    (
        "docs/oneline.md",
        "One line",
        1,
        ["Never call `BaseService` directly. Use `BaseService` only via subclasses."],
        [BASE],
    ),
    (
        "docs/module.md",  # names the module that defines BaseService
        "Module",
        1,
        ["Never import routes in app/_base/service.py."],
        ["app._base.service"],
    ),
    (
        "docs/repos.md",  # names the layer package of UserRepository
        "Repos",
        1,
        ["Code in `app/repos/` must not commit."],
        ["app.repos"],
    ),
    (
        "docs/base.md",  # a package path without a trailing slash; a qualname as a prefix
        "Base",
        1,
        ["Read app._base.service first.", "Never import routes in app/_base."],
        ["app._base"],
    ),
    (
        "docs/create.md",  # a short name used as an English word
        "Create",
        1,
        ["Always create orders through the service.", "`OrderService.create` must validate."],
        ["app.services.order_services.order_service.OrderService.create"],
    ),
    (
        "docs/long.md",  # heading-only mention, long sentence
        "Using BaseService well",
        1,
        [f"In short, {LONG}, so you must always pass them in."],
        [BASE],
    ),
    ("docs/year.md", "Year", 1, ["Never ship in 2024."], []),
]


@pytest.fixture
def reviewed(driver: Driver) -> Driver:
    ensure_schema(driver)
    replace_codebase(driver, with_docs(REVIEW_DOCS))
    return driver


def quotes(result: ChangeCheck, path: str) -> list[tuple[str, int]]:
    return [(g.quote, g.citation.start_line) for g in result.guidelines if g.citation.path == path]


@pytest.fixture
def many(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(change, "MAX_GUIDELINES", 50)


def test_two_sentences_on_one_line_are_both_cited(reviewed: Driver, many: None) -> None:
    result = check(reviewed, "Tidy it up.", ["BaseService"])

    assert quotes(result, "docs/oneline.md") == [
        ("Never call `BaseService` directly.", 2),
        ("Use `BaseService` only via subclasses.", 2),
    ]


def test_the_defining_module_and_the_layer_package_count_as_mentioned(
    reviewed: Driver, many: None
) -> None:
    base = check(reviewed, "Tidy it up.", ["BaseService"])
    repos = check(reviewed, "Tidy it up.", ["UserRepository"])

    assert quotes(base, "docs/module.md") == [("Never import routes in app/_base/service.py.", 2)]
    assert quotes(repos, "docs/repos.md") == [("Code in `app/repos/` must not commit.", 2)]


def test_a_package_path_without_slash_names_it_and_a_qualname_prefix_does_not(
    reviewed: Driver, many: None
) -> None:
    result = check(reviewed, "Tidy it up.", ["BaseService"])

    assert quotes(result, "docs/base.md") == [("Never import routes in app/_base.", 3)]


def test_a_bare_short_name_is_not_a_mention(reviewed: Driver, many: None) -> None:
    result = check(reviewed, "Tidy it up.", ["BaseService"])

    assert quotes(result, "docs/create.md") == [("`OrderService.create` must validate.", 3)]


def test_a_heading_only_quote_is_centered_on_its_modal_word(reviewed: Driver, many: None) -> None:
    result = check(reviewed, "Tidy it up.", ["BaseService"])

    [(quote, _)] = quotes(result, "docs/long.md")
    assert "must always pass them in" in quote
    assert len(quote) <= 200


def test_numbers_are_not_shared_words(reviewed: Driver) -> None:
    result = check(reviewed, "Plan the 2024 release.")

    assert quotes(result, "docs/year.md") == []


def test_the_per_section_cap_holds_across_mention_and_search(
    documented: Driver, many: None
) -> None:
    # mention picks lines 12 and 13; search alone would add 11 and 15
    result = check(documented, "Services read data and call tests.", ["BaseService"])

    assert [line for _, line in quotes(result, "docs/services.md")] == [12, 13]
    assert result.truncated is True  # the cap cut lines 11 and 15


def test_explicit_symbols_are_stripped_and_empty_ones_skipped(indexed: Driver) -> None:
    result = check(indexed, "Tidy it up.", ["get_one", " get_one ", "", "BaseService"])

    assert [a.name for a in result.ambiguous] == ["get_one"]
    assert resolved(result) == [BASE]


def test_candidates_share_one_cap_across_ambiguous_names(
    indexed: Driver, monkeypatch: pytest.MonkeyPatch
) -> None:
    # get_one has 2 candidates, __init__ 3, get 2; 4 in total may be listed
    monkeypatch.setattr(change, "MAX_TOTAL_CANDIDATES", 4)
    result = check(indexed, "Change `get_one`, `__init__` and `get`.")

    assert [(a.name, len(a.candidates)) for a in result.ambiguous] == [
        ("get_one", 2),
        ("__init__", 2),
        ("get", 0),  # still listed: call find_symbol for it
    ]
    assert result.truncated is True


def test_an_ambiguous_name_never_keeps_a_single_candidate(
    indexed: Driver, monkeypatch: pytest.MonkeyPatch
) -> None:
    # after get_one's 2 candidates, 1 is left: too few to choose from, so none are listed
    monkeypatch.setattr(change, "MAX_TOTAL_CANDIDATES", 3)
    result = check(indexed, "Change `get_one`, `__init__` and `get`.")

    assert [(a.name, len(a.candidates)) for a in result.ambiguous] == [
        ("get_one", 2),
        ("__init__", 0),
        ("get", 0),
    ]


def test_an_explicit_symbol_is_at_most_200_characters(indexed: Driver) -> None:
    with pytest.raises(ValueError, match="symbols"):
        check(indexed, "Tidy it up.", ["a" * 201])


ORDER_SERVICE = "app.services.order_services.order_service.OrderService"
# Reviewer run 2 cases.
RUN2_DOCS = [
    (
        "docs/z_base.md",  # app._base encloses BaseService and also imports it
        "Base package",
        1,
        ["Never import routes in app/_base."],
        ["app._base"],
    ),
    (
        "docs/a_order.md",  # a dependent at distance 1
        "Order service",
        1,
        ["`OrderService` must stay thin."],
        [ORDER_SERVICE],
    ),
    (
        "docs/repos_glob.md",  # a glob after a package path does not name it
        "Repos",
        1,
        ["Files in app/repos/*.py hold one repository.", "Never commit in `app/repos/`."],
        ["app.repos"],
    ),
    (
        "docs/mention.md",  # also found by the search below, as its second section
        "Mention",
        1,
        ["Never construct `BaseService` twice, zebra."],
        [BASE],
    ),
    ("docs/search.md", "Search", 1, ["Zebra quagga zebra quagga rules."], []),
]


@pytest.fixture
def run2(driver: Driver) -> Driver:
    ensure_schema(driver)
    replace_codebase(driver, with_docs(RUN2_DOCS))
    return driver


def paths(result: ChangeCheck) -> list[str]:
    return list(dict.fromkeys(g.citation.path for g in result.guidelines))


def test_an_enclosing_module_ranks_as_a_member_even_when_it_imports_the_symbol(
    run2: Driver, many: None
) -> None:
    found = paths(check(run2, "Tidy it up.", ["BaseService"]))

    assert found.index("docs/z_base.md") < found.index("docs/a_order.md")


def test_changing_a_method_reaches_rules_on_its_class(run2: Driver, many: None) -> None:
    result = check(run2, "Tidy it up.", [f"{ORDER_SERVICE}.create"])

    assert quotes(result, "docs/a_order.md") == [("`OrderService` must stay thin.", 2)]


def test_a_glob_after_a_package_path_does_not_name_it(run2: Driver, many: None) -> None:
    result = check(run2, "Tidy it up.", ["UserRepository"])

    assert quotes(result, "docs/repos_glob.md") == [("Never commit in `app/repos/`.", 3)]


def test_a_search_section_past_the_limit_with_nothing_new_is_not_a_cut(
    run2: Driver, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(change, "SEARCH_SECTIONS", 1)
    result = check(run2, "Zebra quagga.", ["BaseService"])

    assert ("Zebra quagga zebra quagga rules.", 2) in quotes(result, "docs/search.md")
    assert result.truncated is False
