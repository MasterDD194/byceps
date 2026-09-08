-- Add the tournament log entries table.
-- Idempotent and transaction-wrapped. Rollback: rollback_012.sql

BEGIN;

CREATE TABLE IF NOT EXISTS lan_tournament_log_entries (
    id UUID NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    event_type TEXT NOT NULL,
    tournament_id UUID NOT NULL,
    initiator_id UUID NULL,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT pk_lan_tournament_log_entries PRIMARY KEY (id),
    CONSTRAINT fk_lan_tournament_log_entries_tournament_id
        FOREIGN KEY (tournament_id) REFERENCES lan_tournaments (id),
    CONSTRAINT fk_lan_tournament_log_entries_initiator_id
        FOREIGN KEY (initiator_id) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS ix_lan_tournament_log_entries_tournament_id
    ON lan_tournament_log_entries (tournament_id);

-- For the retention purge, which filters on occurred_at alone.
CREATE INDEX IF NOT EXISTS ix_lan_tournament_log_entries_occurred_at
    ON lan_tournament_log_entries (occurred_at);

COMMIT;
