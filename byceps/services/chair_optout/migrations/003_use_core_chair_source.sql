-- Back up the database and stop old application/worker processes first.
-- Supports both legacy FK variants and installations without the old table.
BEGIN;

ALTER TABLE tickets ADD COLUMN IF NOT EXISTS chair_source text;

DO $migration$
DECLARE
    conflicting_answers bigint;
    migrated_answers bigint;
    skipped_answers bigint;
BEGIN
    IF to_regclass('party_ticket_chair_optouts') IS NULL THEN
        RETURN;
    END IF;

    LOCK TABLE party_ticket_chair_optouts IN ACCESS EXCLUSIVE MODE;

    SELECT count(*) INTO conflicting_answers
    FROM party_ticket_chair_optouts AS answer
    JOIN tickets AS ticket ON ticket.id = answer.ticket_id
    WHERE ticket.party_id = answer.party_id
      AND ticket.used_by_id = answer.user_id
      AND NOT ticket.revoked
      AND ticket.chair_source IS NOT NULL
      AND ticket.chair_source IS DISTINCT FROM
          CASE WHEN answer.brings_own_chair THEN 'user' ELSE 'venue' END;

    IF conflicting_answers > 0 THEN
        RAISE EXCEPTION '% existing Core chair sources conflict with legacy answers. Resolve them before retrying.', conflicting_answers;
    END IF;

    SELECT count(*) INTO skipped_answers
    FROM party_ticket_chair_optouts AS answer
    WHERE NOT EXISTS (
        SELECT 1 FROM tickets AS ticket
        WHERE ticket.id = answer.ticket_id
          AND ticket.party_id = answer.party_id
          AND ticket.used_by_id = answer.user_id
          AND NOT ticket.revoked
    );

    UPDATE tickets AS ticket
    SET chair_source =
        CASE WHEN answer.brings_own_chair THEN 'user' ELSE 'venue' END
    FROM party_ticket_chair_optouts AS answer
    WHERE ticket.id = answer.ticket_id
      AND ticket.party_id = answer.party_id
      AND ticket.used_by_id = answer.user_id
      AND NOT ticket.revoked
      AND ticket.chair_source IS NULL;
    GET DIAGNOSTICS migrated_answers = ROW_COUNT;

    IF EXISTS (
        SELECT 1
        FROM party_ticket_chair_optouts AS answer
        JOIN tickets AS ticket ON ticket.id = answer.ticket_id
        WHERE ticket.party_id = answer.party_id
          AND ticket.used_by_id = answer.user_id
          AND NOT ticket.revoked
          AND ticket.chair_source IS DISTINCT FROM
              CASE WHEN answer.brings_own_chair THEN 'user' ELSE 'venue' END
    ) THEN
        RAISE EXCEPTION 'Chair answer verification failed; the legacy table has been retained.';
    END IF;

    DROP TABLE party_ticket_chair_optouts;
    RAISE NOTICE 'Migrated % chair answers; skipped % invalid legacy answers.', migrated_answers, skipped_answers;
END
$migration$;

COMMIT;
