-- Drop the tournament FK from log entries so they survive their
-- tournament's deletion. The column and its index stay.
-- Idempotent and transaction-wrapped. Rollback: rollback_013.sql

BEGIN;

ALTER TABLE lan_tournament_log_entries
    DROP CONSTRAINT IF EXISTS fk_lan_tournament_log_entries_tournament_id;

COMMIT;
