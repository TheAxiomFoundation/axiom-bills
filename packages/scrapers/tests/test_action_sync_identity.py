"""Fresh scraper databases must not multiply remote bill events."""
from datetime import datetime
from types import SimpleNamespace
from axiom_bills._common import db, supabase_sync as sync


def action(local_bill, local_action, remote_bill='remote-bill', when='2026-07-01T00:00:00'):
    event = SimpleNamespace(occurred_at=datetime.fromisoformat(when), action_text='Passed House')
    return dict(id=local_action, bill_id=remote_bill, occurred_at=when,
                action_text=event.action_text, fingerprint=db._fingerprint(local_bill, event))


def test_fresh_databases_reproduce_old_mismatch_and_now_reuse_remote_event(monkeypatch):
    first, second = action('local-bill-1', 'local-action-1'), action('local-bill-2', 'local-action-2')
    assert first['fingerprint'] != second['fingerprint']  # reproduced original defect
    remote = []
    monkeypatch.setattr(sync, '_remote_rows_by_in', lambda *a, **k: list(remote))
    remote.extend(sync._prepare_remote_actions(object(), [first]))
    again = sync._prepare_remote_actions(object(), [second])
    assert again[0]['id'] == remote[0]['id']
    assert again[0]['fingerprint'] == remote[0]['fingerprint']
    assert first['id'] == 'local-action-1'  # local records are not rewritten


def test_legacy_duplicates_reuse_one_survivor_without_adding_or_deleting(monkeypatch):
    legacy = [action('old-2', 'b'), action('old-1', 'a', when='2026-07-01T00:00:00+00:00')]
    monkeypatch.setattr(sync, '_remote_rows_by_in', lambda *a, **k: legacy)
    result = sync._prepare_remote_actions(object(), [action('new', 'c')])
    assert result[0]['id'] == 'a'
    assert result[0]['fingerprint'] == legacy[1]['fingerprint']
    assert len(legacy) == 2


def test_empty_remote_and_parallel_preparation_are_stable_and_deduplicated(monkeypatch):
    monkeypatch.setattr(sync, '_remote_rows_by_in', lambda *a, **k: [])
    a, b = action('a','a'), action('b','b',when='2026-06-30T20:00:00-04:00')
    x=sync._prepare_remote_actions(object(),[a,b]);y=sync._prepare_remote_actions(object(),[b])
    assert len(x)==1
    assert x[0]['id']==y[0]['id'] and x[0]['fingerprint']==y[0]['fingerprint']


def test_distinct_bills_dates_and_exact_text_remain_distinct(monkeypatch):
    monkeypatch.setattr(sync, '_remote_rows_by_in', lambda *a, **k: [])
    rows=[action('a','a'),action('b','b',remote_bill='other-bill'),action('c','c',when='2026-07-02T00:00:00')]
    rows.append({**rows[0], 'action_text':'Passed Senate'})
    assert len(sync._prepare_remote_actions(object(),rows))==4
