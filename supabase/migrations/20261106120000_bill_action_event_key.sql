-- One row per action on a bill, at the database's level.
--
-- The sync already finds an action by bill, moment and text before it writes. This
-- index holds any other writer to the same rule. It hashes the text because action
-- text can outgrow a btree entry.
--
-- On production, supabase/manual/bill_action_cleanup.sql adds this index to the
-- table it builds, and this file then does nothing. Building it on the table with
-- the old copies would run for hours and then fail on the first copy, so this file
-- refuses a table that size.

do $$
begin
  if to_regclass('bills.bill_actions_event_key') is not null then
    return;
  end if;
  if (select reltuples from pg_class where oid = 'bills.bill_actions'::regclass) > 5000000 then
    raise exception 'bills.bill_actions still holds its old copies: run supabase/manual/bill_action_cleanup.py first';
  end if;
  create unique index bill_actions_event_key
    on bills.bill_actions (bill_id, occurred_at, md5(action_text));
end
$$;
