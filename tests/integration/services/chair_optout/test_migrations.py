"""
:License: Revised BSD (see `LICENSE` file for details)
"""

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError

from byceps.database import db


MIGRATION = Path(
    'byceps/services/chair_optout/migrations/003_use_core_chair_source.sql'
)


@pytest.fixture
def connection(admin_app):
    schema = f'chair_migration_{uuid4().hex}'
    with db.engine.connect().execution_options(
        isolation_level='AUTOCOMMIT'
    ) as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA {schema}')
        try:
            connection.exec_driver_sql(f'SET search_path TO {schema}')
            connection.exec_driver_sql("""
                CREATE TABLE tickets (
                    id uuid PRIMARY KEY,
                    party_id text NOT NULL,
                    used_by_id uuid,
                    revoked boolean NOT NULL DEFAULT false
                )
            """)
            yield connection
        finally:
            connection.exec_driver_sql('ROLLBACK')
            connection.exec_driver_sql('SET search_path TO public')
            connection.exec_driver_sql(f'DROP SCHEMA {schema} CASCADE')


def _create_legacy_table(connection, cascade=False):
    ondelete = 'ON DELETE CASCADE' if cascade else ''
    connection.exec_driver_sql(f"""
        CREATE TABLE party_ticket_chair_optouts (
            id uuid PRIMARY KEY,
            party_id text NOT NULL,
            ticket_id uuid NOT NULL REFERENCES tickets(id) {ondelete},
            user_id uuid NOT NULL,
            brings_own_chair boolean NOT NULL,
            updated_at timestamp NOT NULL,
            UNIQUE (party_id, ticket_id)
        )
    """)
    connection.exec_driver_sql("""
        CREATE INDEX legacy_chair_ticket_id
        ON party_ticket_chair_optouts (ticket_id)
    """)


def _add_answer(
    connection,
    own,
    *,
    revoked=False,
    unassigned=False,
    stale=False,
    wrong_party=False,
):
    ticket_id, user_id = uuid4(), uuid4()
    participant_id = None if unassigned else uuid4() if stale else user_id
    connection.exec_driver_sql(
        'INSERT INTO tickets (id, party_id, used_by_id, revoked) '
        'VALUES (%s, %s, %s, %s)',
        (ticket_id, 'party', participant_id, revoked),
    )
    connection.exec_driver_sql(
        'INSERT INTO party_ticket_chair_optouts '
        '(id, party_id, ticket_id, user_id, brings_own_chair, updated_at) '
        'VALUES (%s, %s, %s, %s, %s, now())',
        (uuid4(), 'other' if wrong_party else 'party', ticket_id, user_id, own),
    )
    return ticket_id


def _migrate(connection):
    connection.exec_driver_sql(
        MIGRATION.read_text(), execution_options={'no_parameters': True}
    )


@pytest.mark.parametrize('cascade', [False, True])
def test_transition_migrates_only_valid_answers_and_removes_legacy_table(
    connection, cascade
):
    _create_legacy_table(connection, cascade)
    own = _add_answer(connection, True)
    venue = _add_answer(connection, False)
    skipped = [
        _add_answer(connection, True, **scenario)
        for scenario in [
            {'revoked': True},
            {'unassigned': True},
            {'stale': True},
            {'wrong_party': True},
        ]
    ]
    _migrate(connection)
    sources = dict(
        connection.exec_driver_sql('SELECT id, chair_source FROM tickets').all()
    )
    assert sources[own] == 'user'
    assert sources[venue] == 'venue'
    assert all(sources[ticket_id] is None for ticket_id in skipped)
    assert (
        connection.exec_driver_sql(
            "SELECT to_regclass('party_ticket_chair_optouts')"
        ).scalar_one()
        is None
    )
    assert (
        connection.exec_driver_sql(
            "SELECT to_regclass('legacy_chair_ticket_id')"
        ).scalar_one()
        is None
    )
    _migrate(connection)
    assert (
        dict(
            connection.exec_driver_sql(
                'SELECT id, chair_source FROM tickets'
            ).all()
        )
        == sources
    )


@pytest.mark.parametrize('column_exists', [False, True])
def test_transition_supports_no_legacy_table(connection, column_exists):
    if column_exists:
        connection.exec_driver_sql(
            'ALTER TABLE tickets ADD COLUMN chair_source text'
        )
    ticket_id = uuid4()
    connection.exec_driver_sql(
        "INSERT INTO tickets (id, party_id) VALUES (%s, 'party')", (ticket_id,)
    )
    _migrate(connection)
    connection.exec_driver_sql(
        "UPDATE tickets SET chair_source = 'rental' WHERE id = %s", (ticket_id,)
    )
    _migrate(connection)
    assert (
        connection.exec_driver_sql(
            'SELECT chair_source FROM tickets WHERE id = %s', (ticket_id,)
        ).scalar_one()
        == 'rental'
    )


def test_transition_preserves_matching_core_value(connection):
    _create_legacy_table(connection)
    ticket_id = _add_answer(connection, True)
    connection.exec_driver_sql(
        'ALTER TABLE tickets ADD COLUMN chair_source text'
    )
    connection.exec_driver_sql(
        "UPDATE tickets SET chair_source = 'user' WHERE id = %s", (ticket_id,)
    )
    _migrate(connection)
    assert (
        connection.exec_driver_sql(
            'SELECT chair_source FROM tickets WHERE id = %s', (ticket_id,)
        ).scalar_one()
        == 'user'
    )


@pytest.mark.parametrize('existing', ['venue', 'rental'])
def test_conflicting_core_value_rolls_back_transition(connection, existing):
    _create_legacy_table(connection)
    conflicting = _add_answer(connection, True)
    pending = _add_answer(connection, False)
    connection.exec_driver_sql(
        'ALTER TABLE tickets ADD COLUMN chair_source text'
    )
    connection.exec_driver_sql(
        'UPDATE tickets SET chair_source = %s WHERE id = %s',
        (existing, conflicting),
    )
    with pytest.raises(DBAPIError) as error:
        _migrate(connection)
    assert error.value.orig.sqlstate == 'P0001'
    assert 'conflict with legacy answers' in str(error.value.orig)
    connection.exec_driver_sql('ROLLBACK')
    assert (
        connection.exec_driver_sql(
            'SELECT count(*) FROM party_ticket_chair_optouts'
        ).scalar_one()
        == 2
    )
    sources = dict(
        connection.exec_driver_sql('SELECT id, chair_source FROM tickets').all()
    )
    assert sources[conflicting] == existing
    assert sources[pending] is None
