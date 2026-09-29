BEGIN;

ALTER TABLE party_ticket_chair_optouts
    DROP CONSTRAINT party_ticket_chair_optouts_ticket_id_fkey;

ALTER TABLE party_ticket_chair_optouts
    ADD CONSTRAINT party_ticket_chair_optouts_ticket_id_fkey
    FOREIGN KEY (ticket_id) REFERENCES tickets(id) ON DELETE CASCADE;

COMMIT;
