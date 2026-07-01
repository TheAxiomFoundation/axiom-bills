"""Tests for legislative-stage ranking of bill version labels."""

from __future__ import annotations

from axiom_bills._common.version_rank import stage_rank


def test_federal_stage_order():
    labels = [
        "Introduced in House",
        "Referred in Senate",
        "Reported in House",
        "Engrossed in House",
        "Enrolled Bill",
        "Public Law",
    ]
    ranks = [stage_rank(x) for x in labels]
    assert ranks == sorted(ranks), ranks
    assert len(set(ranks)) == len(ranks)


def test_alphabetical_trap():
    """The bug: 'Engrossed in House' < 'Introduced in House'
    alphabetically, so ORDER BY label picked the engrossed text even
    after enrollment — and vice versa for other label pairs."""
    assert stage_rank("Enrolled Bill") > stage_rank("Engrossed in Senate")
    assert stage_rank("Engrossed in Senate") > stage_rank("Introduced in House")


def test_unknown_labels_rank_zero():
    assert stage_rank("Some Novel Label") == 0
    assert stage_rank(None) == 0
    assert stage_rank("") == 0
