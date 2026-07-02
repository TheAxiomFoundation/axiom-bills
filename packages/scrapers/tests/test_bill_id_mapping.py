"""Tests for local→remote bill id mapping (supabase sync).

Regression: bill numbers repeat across Congresses. Scraping the 119th's
H.R.7024 while the remote row was the 118th's H.R.7024 made the
session-fallback adopt the OLD bill's primary key; the natural-key
upsert then tried to INSERT with that id → 23505, aborting the sync
(and losing that run's freshly drafted variants).
"""

from __future__ import annotations

from axiom_bills._common.supabase_sync import _map_bill_ids


REMOTE = [{"id": "R1", "jurisdiction": "us", "session_id": "S118",
           "chamber": "lower", "number": "H.R.7024"}]


def _local(session_id):
    return [{"id": "L1", "jurisdiction": "us", "session_id": session_id,
             "chamber": "lower", "number": "H.R.7024"}]


def test_exact_match_adopts_remote_id():
    mapped = _map_bill_ids(_local("S118"), REMOTE, {"S118", "S119"})
    assert mapped["L1"] == "R1"


def test_rekeyed_session_falls_back():
    """Local session name unknown remotely (re-key) → same bill, adopt."""
    mapped = _map_bill_ids(_local("S118-old-key"), REMOTE, {"S118"})
    assert mapped["L1"] == "R1"


def test_same_number_different_congress_is_a_new_bill():
    """The H.R.7024 crash: local session EXISTS remotely (119th), so a
    number-only match against the 118th bill must NOT adopt its PK."""
    mapped = _map_bill_ids(_local("S119"), REMOTE, {"S118", "S119"})
    assert mapped["L1"] == "L1"


def test_ambiguous_fallback_never_adopts():
    remote = REMOTE + [{"id": "R2", "jurisdiction": "us", "session_id": "S117",
                        "chamber": "lower", "number": "H.R.7024"}]
    mapped = _map_bill_ids(_local("S-unknown"), remote, {"S117", "S118"})
    assert mapped["L1"] == "L1"
