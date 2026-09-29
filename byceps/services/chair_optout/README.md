# Participant chair information

This service lets the current participant of each party ticket state whether
they will bring their own chair or need a provided chair.

## Participant rules

- A chair answer belongs to the ticket's current `used_by` participant.
- Ticket ownership and seat or user management rights do not grant access.
- Tickets without seats can be answered.
- A seat change preserves the answer.
- A ticket-user change clears the previous answer. The new participant
  starts with no answer and supplies a new ticket-level record when they
  submit one.

## Administration

The party-specific `More` page links to `Seat management`. Its first tool is
`Participant chair information`, which provides summary counts, a participant
table, CSV export, and graphical seating plans. The participant table can be
filtered by answer state or missing seat and links to the corresponding user,
ticket, and seat views.

The graphical seating plans show the participant and chair status in each
occupied seat's tooltip. A green inner outline and dot mark participants who
bring their own chair.

The overview and export use the existing `seating.view` permission. There is no
Chair-specific permission or role.

The three answer-state summary values partition all non-revoked party tickets
with a current participant. `No seat` is an additional count over the same
tickets, so a ticket without a seat is also counted in exactly one answer state.

Public seat links prefer the party's `primary_party_site_id`. Without that
setting, a link is offered only if there is exactly one enabled, unarchived
site for the party. Links use HTTPS, as do BYCEPS's other cross-site links.
The administrative plan loads the primary site's `static/style/seating.css`
when present. If no primary site is configured, it loads a stylesheet only
when exactly one site associated with the party provides one.
Without a matching stylesheet, the core seat dimensions are used.

## Persistence

Answers are stored in `party_ticket_chair_optouts`, with one row per party and
ticket. The row stores the participant ID that supplied the current answer.
Reads treat a row as valid only while its `user_id` matches the ticket's current
`used_by_id`. A feature-local SQLAlchemy handler removes the answer during
Ticketing's participant update, in the same transaction. Returning a ticket to
a previous participant does not restore an old answer. Saving locks the ticket
until commit, so reassignment, revocation, and concurrent answers are serialized.
Use the Ticketing services for participant changes; bulk SQL updates bypass ORM
handlers. Deleting a ticket also deletes its dependent chair answer.

Before deploying, apply these migrations in order to the site database:

1. `migrations/001_create_party_ticket_chair_optouts.sql`
2. `migrations/002_cascade_ticket_deletion.sql`

Existing installations with migration 001 need only migration 002. The matching
`rollback_002.sql` restores the non-cascading ticket foreign key;
`rollback_001.sql` removes the table and all stored chair answers.

German UI translations are stored in `byceps/translations/de/LC_MESSAGES/messages.po`.
The Docker image compiles the catalog before installing the application. For a
local installation, run `just babel-compile` after pulling changes; do not
commit the generated `messages.mo`.

The three states are:

- no valid row for the current participant: not specified yet;
- `brings_own_chair = true`: brings own chair;
- `brings_own_chair = false`: needs a provided chair.

Seat labels and seating-plan positions are resolved from the current Seating
data and are not duplicated in the Chair table.

## Validation

Use the repository commands documented in the root `justfile`, `pyproject.toml`,
and CI workflow. Chair tests are located below these paths:

- `tests/unit/blueprints/chair_optout`;
- `tests/unit/services/chair_optout`;
- `tests/integration/blueprints/admin/chair_optout`;
- `tests/integration/blueprints/site/chair_optout`;
- `tests/integration/services/chair_optout`.

Integration tests must use a dedicated PostgreSQL database and Redis instance;
their setup drops database tables. Set `POSTGRES_HOST`, `POSTGRES_PORT`,
`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `REDIS_HOST`, and
`REDIS_PORT` for the test environment before running pytest.

The browser regression checks exercise the shared tooltip JavaScript and seat
styles in Chromium (server-side template rendering is covered by integration
tests). Run this from the repository root:

```sh
docker run --rm --ipc=host -v "$PWD:/repo:ro" -w /repo \
  mcr.microsoft.com/playwright:v1.56.1-noble sh -c \
  'npm install --prefix /tmp --ignore-scripts --no-package-lock playwright@1.56.1 && NODE_PATH=/tmp/node_modules node tests/browser/chair_tooltips.cjs'
```
