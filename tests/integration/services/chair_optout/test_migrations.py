"""
:License: Revised BSD (see `LICENSE` file for details)
"""

from pathlib import Path
from uuid import uuid4

from byceps.database import db


def test_migrations_upgrade_cascade_and_rollback(admin_app):
    migrations = Path('byceps/services/chair_optout/migrations')
    schema = f'chair_migration_{uuid4().hex}'
    with db.engine.connect().execution_options(
        isolation_level='AUTOCOMMIT'
    ) as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA {schema}')
        try:
            connection.exec_driver_sql(f'SET search_path TO {schema}')
            for table, type_ in [
                ('parties', 'TEXT'),
                ('tickets', 'UUID'),
                ('users', 'UUID'),
            ]:
                connection.exec_driver_sql(
                    f'CREATE TABLE {table} (id {type_} PRIMARY KEY)'
                )
            connection.exec_driver_sql(
                (
                    migrations / '001_create_party_ticket_chair_optouts.sql'
                ).read_text()
            )
            connection.exec_driver_sql(
                (migrations / '002_cascade_ticket_deletion.sql').read_text()
            )
            ticket_id, user_id, answer_id = (
                str(uuid4()),
                str(uuid4()),
                str(uuid4()),
            )
            connection.exec_driver_sql("INSERT INTO parties VALUES ('party')")
            connection.exec_driver_sql(
                'INSERT INTO tickets VALUES (%s)', (ticket_id,)
            )
            connection.exec_driver_sql(
                'INSERT INTO users VALUES (%s)', (user_id,)
            )
            connection.exec_driver_sql(
                'INSERT INTO party_ticket_chair_optouts '
                '(id, party_id, ticket_id, user_id, brings_own_chair, updated_at) '
                "VALUES (%s, 'party', %s, %s, true, now())",
                (answer_id, ticket_id, user_id),
            )
            connection.exec_driver_sql(
                'DELETE FROM tickets WHERE id = %s', (ticket_id,)
            )
            assert (
                connection.exec_driver_sql(
                    'SELECT count(*) FROM party_ticket_chair_optouts'
                ).scalar_one()
                == 0
            )
            connection.exec_driver_sql(
                (migrations / 'rollback_002.sql').read_text()
            )
            assert (
                connection.exec_driver_sql(
                    'SELECT confdeltype FROM pg_constraint WHERE conrelid = '
                    "'party_ticket_chair_optouts'::regclass AND "
                    "conname = 'party_ticket_chair_optouts_ticket_id_fkey'"
                ).scalar_one()
                == 'a'
            )
            connection.exec_driver_sql(
                (migrations / 'rollback_001.sql').read_text()
            )
        finally:
            connection.exec_driver_sql('ROLLBACK')
            connection.exec_driver_sql('SET search_path TO public')
            connection.exec_driver_sql(f'DROP SCHEMA {schema} CASCADE')
