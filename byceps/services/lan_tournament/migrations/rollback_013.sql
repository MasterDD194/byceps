-- Reverse migration 013: restore the FK from log entries to their
-- tournament.
--
-- This fails if any entry outlived its tournament, which is expected
-- after 013. It deliberately does not delete those audit entries;
-- decide what to do with them first.

BEGIN;

ALTER TABLE lan_tournament_log_entries
    ADD CONSTRAINT fk_lan_tournament_log_entries_tournament_id
        FOREIGN KEY (tournament_id) REFERENCES lan_tournaments (id);

COMMIT;
