"""
tests.integration.services.lan_tournament.test_log_entry_purge
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, update

from byceps.database import db
from byceps.services.lan_tournament import (
    tournament_log_service,
    tournament_service,
)
from byceps.services.lan_tournament.dbmodels.tournament_log_entry import (
    DbTournamentLogEntry,
)
from byceps.services.lan_tournament.models import ContestantType
from byceps.services.party.models import PartyID


PARTY_ID = PartyID('lan-party-2024-logpurge')


@pytest.fixture(scope='module')
def party(make_party, brand):
    return make_party(brand, PARTY_ID, 'LAN Party 2024 Log Purge')


@pytest.fixture(scope='module')
def initiator(make_user):
    return make_user('LogPurgeInitiator')


@pytest.fixture(scope='module')
def tournament(party):
    result = tournament_service.create_tournament(
        PARTY_ID,
        'Log Purge Test Tournament',
        contestant_type=ContestantType.SOLO,
    )
    assert result.is_ok()
    tournament, _ = result.unwrap()
    return tournament


@pytest.fixture(autouse=True)
def _isolated_log_table():
    """Start every test with an empty log table.

    The purge is global, and the tests assert exact counts.
    """
    db.session.execute(delete(DbTournamentLogEntry))
    db.session.commit()
    yield
    db.session.execute(delete(DbTournamentLogEntry))
    db.session.commit()


def _seed_entry(tournament, initiator, event_type: str) -> None:
    tournament_log_service.create_log_entry(
        event_type, tournament.id, initiator.id
    )


def _set_age(event_type: str, days: int) -> None:
    occurred_at = datetime.now(UTC) - timedelta(days=days)
    db.session.execute(
        update(DbTournamentLogEntry)
        .where(DbTournamentLogEntry.event_type == event_type)
        .values(occurred_at=occurred_at)
    )
    db.session.commit()


def _count_entries() -> int:
    return len(
        db.session.scalars(select(DbTournamentLogEntry)).all()
    )


def test_purge_deletes_only_entries_older_than_cutoff(tournament, initiator):
    _seed_entry(tournament, initiator, 'purge-old-entry')
    _seed_entry(tournament, initiator, 'purge-recent-entry')
    _set_age('purge-old-entry', 400)
    _set_age('purge-recent-entry', 1)

    cutoff = datetime.now(UTC) - timedelta(days=365)

    result = tournament_log_service.purge_entries_older_than(cutoff)
    assert result.is_ok()

    remaining = [
        e.event_type
        for e in tournament_log_service.get_entries_for_tournament(
            tournament.id
        )
    ]
    assert 'purge-old-entry' not in remaining
    assert 'purge-recent-entry' in remaining


def test_purge_returns_deleted_row_count(tournament, initiator):
    """Purge exactly the one old entry."""
    assert _count_entries() == 0

    _seed_entry(tournament, initiator, 'purge-count-entry')
    _set_age('purge-count-entry', 400)

    cutoff = datetime.now(UTC) - timedelta(days=365)

    result = tournament_log_service.purge_entries_older_than(cutoff)
    assert result.is_ok()
    assert result.unwrap() == 1
    assert _count_entries() == 0


def test_purge_on_empty_table_returns_zero():
    """Purge nothing from an empty table."""
    assert _count_entries() == 0

    cutoff = datetime.now(UTC) - timedelta(days=365)

    result = tournament_log_service.purge_entries_older_than(cutoff)
    assert result.is_ok()
    assert result.unwrap() == 0


def test_purge_deletes_orphaned_entries_by_age_alone(party, initiator):
    """Purge an entry whose tournament was deleted like any other."""
    result = tournament_service.create_tournament(
        PARTY_ID,
        'Orphan Source Tournament',
        contestant_type=ContestantType.SOLO,
    )
    assert result.is_ok()
    orphan_tournament, _ = result.unwrap()

    _seed_entry(orphan_tournament, initiator, 'purge-orphan-entry')
    _set_age('purge-orphan-entry', 400)

    # Orphan the entry by deleting its tournament.
    tournament_service.delete_tournament(orphan_tournament.id)
    assert tournament_service.find_tournament(orphan_tournament.id) is None

    remaining_event_types = {
        e.event_type
        for e in tournament_log_service.get_entries_for_tournament(
            orphan_tournament.id
        )
    }
    assert 'purge-orphan-entry' in remaining_event_types
    # The fresh `tournament-deleted` entry must not be purged.
    assert 'tournament-deleted' in remaining_event_types

    cutoff = datetime.now(UTC) - timedelta(days=365)

    result = tournament_log_service.purge_entries_older_than(cutoff)
    assert result.is_ok()
    assert result.unwrap() == 1

    remaining_event_types = {
        e.event_type
        for e in tournament_log_service.get_entries_for_tournament(
            orphan_tournament.id
        )
    }
    assert 'purge-orphan-entry' not in remaining_event_types
    assert 'tournament-deleted' in remaining_event_types
