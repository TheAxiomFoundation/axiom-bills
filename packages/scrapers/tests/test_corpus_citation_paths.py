"""citation_to_path and _parent_paths build the paths the corpus stores."""
import pytest

from axiom_bills._common.corpus_client import _parent_paths, citation_to_path


@pytest.mark.parametrize("citation, path", [
    ("26 USC 213", "us/statute/26/213"),
    ("26 USC 213(a)(1)", "us/statute/26/213/a/1"),
    ("42 USC 300hh-14", "us/statute/42/300hh-14"),
    # The corpus stores a CFR part and section as separate segments.
    ("7 CFR 273.9", "us/regulation/7/273/9"),
    ("7 CFR 273.3(b)(2)", "us/regulation/7/273/3/b/2"),
    ("42 CFR 435.603", "us/regulation/42/435/603"),
    ("26 CFR 1.1-1", None),  # hyphenated CFR sections are not mapped yet
    ("Social Security Act 1902", None),
])
def test_citation_to_path(citation, path):
    assert citation_to_path(citation) == path


def test_cfr_path_has_no_dotted_segment():
    path = citation_to_path("45 CFR 155.305(f)")
    assert path == "us/regulation/45/155/305/f"
    assert all("." not in segment for segment in path.split("/"))


def test_statute_fallback_stops_at_the_section():
    assert _parent_paths("us/statute/26/3121/a/1") == [
        "us/statute/26/3121/a", "us/statute/26/3121",
    ]
    assert _parent_paths("us/statute/26/3121") == []


def test_regulation_fallback_stops_at_the_section_not_the_part():
    assert _parent_paths("us/regulation/7/273/3/b/2") == [
        "us/regulation/7/273/3/b", "us/regulation/7/273/3",
    ]
    assert _parent_paths("us/regulation/7/273/3") == []
