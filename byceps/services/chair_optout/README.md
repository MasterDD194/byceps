# Participant chair information

This extension adds organizer reports and participant reminders to BYCEPS Core's
per-ticket chair selection. It requires Core commits `8fc0d8a91` and `ad9f93483`
or a later version containing them. Core writes and ticket services are reused
without local modifications.

## Core data and participant interface

The only answer storage is `tickets.chair_source`:

- `user`: brings their own chair;
- `venue`: needs a chair provided by the location;
- `rental`: reports a rented chair;
- `NULL`: has not specified a source.

GV36 offers only own/venue chairs on `My tickets`. It has no manual answer reset,
rental offering, booking validation, order association, or separate chair form.
An existing rental source is displayed distinctly and remains available in
organizer reports. Participant POST requests allow only `user` and `venue`;
`NULL` remains the initial status and is restored automatically on user changes.
Legacy `/chair_optout/` GET links redirect to `My tickets`.

The GV36 dashboard and seating templates link to the first unanswered ticket.
Multiple pending tickets are counted on the dashboard. Only currently used,
non-revoked, unchecked-in tickets are eligible, and hints are hidden when ticket
management is disabled. Ownership or management of someone else's ticket does
not grant permission to answer for that participant. Own-profile information is
rendered in the site override using the tickets already provided by Core.

## Transactions and ticket lifecycle

A request hook guards only Core's `ticketing.set_chair_source` POST endpoint.
It locks and refreshes the ticket before checking current party, participant,
revocation and check-in state and restricts participant choices to own/venue
chairs. Core performs the chair update and ticket-log write and commits once.
Request/session teardown rolls back failed requests.

A feature-local mapper listener resets the source in the participant-change
transaction. It compares the database-current participant under a row lock with
the intended participant, preserving answers on duplicate appointments. It
forces a reset even if a stale ORM instance had already loaded a `NULL` source.
Seat changes retain answers; changing or withdrawing the participant clears
them, and returning to a previous participant does not restore an old answer.

`application.py` registers the listener idempotently for all application modes,
including CLI and worker. Participant changes must use the normal ORM ticket
services: bulk SQL updates bypass mapper listeners. The HTTP guard applies to
the Core chair route; direct service calls must validate/lock their own access.
Automatic participant-change resets accompany the existing participant log,
while explicit selections use Core's `chair-source-set` ticket event.

## Administration

The party's `More` page links to `Seat management`, then `Participant chair
information`. Reports use `seating.view` for the list, plan and CSV.

Source counts partition non-revoked party tickets with a current participant.
`No seat` is an overlapping additional count, not another source category.
Rental controls are shown only when rental records exist. Unknown answers are
never counted as confirmed venue-chair demand.

The plan loads a compact ticket/source map instead of the participant report.
Filters dim nonmatching seats without removing geometry. The no-seat filter
is available only in the participant list. Own chairs have a green outline/dot,
venue chairs a blue marker, and unknown/rental sources have distinct markers and text
tooltips. The module-local tooltip script uses DOM text nodes, independently of
Core seating behavior. CSV cells retain formula-injection escaping.

GV36 chair choices use Core POST requests followed by a background page fetch
that consumes Core's flash message. The saved source and confirmation are shown
at the affected ticket without navigation or a scroll jump. Selecting the
already saved source only closes the menu, without another request. Failed
requests retain the displayed answer and show a localized inline error. Open
ticket dropdowns remain above other ticket cards and the footer in both themes.

Public seat links use the party's `primary_party_site_id`, or the unique current
site if no primary site is configured, and use HTTPS like Core cross-site links.
The plan uses that site's seating stylesheet when available. Without a primary
site it uses the unique party-site stylesheet; ambiguous choices are not guessed.
Stylesheet paths are validated and Core seat dimensions are the fallback.

## Upgrade from the legacy answer table

Back up the database under `runtime/backups/` and stop old application and worker
processes before running:

```sh
psql -X -v ON_ERROR_STOP=1 "$DATABASE_URL" \
  -f byceps/services/chair_optout/migrations/003_use_core_chair_source.sql
```

The single transaction adds Core's column if missing, converts valid legacy
answers (`true` to `user`, `false` to `venue`), verifies them and drops
`party_ticket_chair_optouts` with its indexes/constraints. Validity requires the
same party and current participant and a non-revoked ticket. Invalid/stale rows
are skipped. Matching existing Core values are retained; conflicting values
abort the entire transition so they can be resolved before retrying.

Both old foreign-key variants are supported; applying the retired cascade
migration first is unnecessary. Re-running the transition or running it without
the legacy table preserves Core answers. Fresh installations create the Core
ticket column normally and have no extension-specific database tables.

Rollback of the legacy removal uses the database backup and the matching old
application version. No lossy reverse migration is supplied. Never remove the
Core column as an extension rollback.

## Validation

Integration tests drop tables. Use a disposable PostgreSQL database and Redis,
never the shared runtime. Configure `POSTGRES_HOST`, `POSTGRES_PORT`,
`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `REDIS_HOST`, and `REDIS_PORT`.

```sh
uv sync --frozen --group test
uv run --no-sync pytest tests/unit/services/chair_optout \
  tests/unit/blueprints/chair_optout tests/integration/services/chair_optout \
  tests/integration/blueprints/admin/chair_optout \
  tests/integration/blueprints/site/chair_optout \
  tests/integration/blueprints/site/dashboard \
  tests/integration/blueprints/site/user_profile
uv run --no-sync coverage run --source=byceps -m pytest tests
```

The tests exercise sources, eligibility, migration/rollback, locking and stale
instances, concurrent answers/appointments, Core log writes, theme reminders,
filters, CSV, and fresh CLI/worker registration. Run browser regressions from
the repository root:

```sh
docker run --rm --ipc=host -v "$PWD:/repo:ro" -w /repo \
  mcr.microsoft.com/playwright:v1.56.1-noble sh -c \
  'npm install --prefix /tmp --ignore-scripts --no-package-lock playwright@1.56.1 && NODE_PATH=/tmp/node_modules node tests/browser/chair_tooltips.cjs'
```

Ticket interaction regressions render the actual GV36 templates without a
database and simulate only Core's HTTP response. They cover light/dark desktop
and mobile layouts, dropdown hit targets over cards/footer, inline confirmation
without navigation, compatibility with older markup, repeated selections,
persistence after reload, the initial unknown status, and failed-save retry. Store
the generated fixture in the local runtime directory:

```sh
FIXTURE=/path/to/runtime/ticket-chair-browser-fixture.json
uv run --no-sync python tests/browser/render_ticket_chair_fixture.py > "$FIXTURE"
docker run --rm --ipc=host -v "$PWD:/repo:ro" \
  -v "$FIXTURE:/fixtures/tickets.json:ro" -w /repo \
  mcr.microsoft.com/playwright:v1.56.1-noble sh -c \
  'npm install --prefix /tmp --ignore-scripts --no-package-lock playwright@1.56.1 && NODE_PATH=/tmp/node_modules node tests/browser/ticket_chair_interactions.cjs /fixtures/tickets.json'
```

German translations remain in `byceps/translations/de/LC_MESSAGES/messages.po`.
The Docker build compiles the catalogue; local installs can use
`just babel-compile`. Never commit generated `messages.mo`.
