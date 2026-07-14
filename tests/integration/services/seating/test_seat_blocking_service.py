"""
:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from dataclasses import dataclass, field
from uuid import UUID

import pytest
from sqlalchemy import select

from byceps.database import db
from byceps.services.seating.dbmodels.seat import DbSeat
from byceps.services.seating.management import service
from byceps.services.seating.management.errors import (
    SeatNotFoundError,
    SeatOccupiedError,
    SeatOutsideAreaError,
)
from byceps.services.seating.models import SeatID
from byceps.services.ticketing.errors import (
    SeatChangeDeniedForGroupSeatError,
)

from tests.helpers import generate_uuid


@dataclass
class RecordingLog:
    entries: list[tuple[str, dict]] = field(default_factory=list)
    persisted_states: list[bool] = field(default_factory=list)

    def info(self, event: str, **data) -> None:
        self.entries.append((event, data))
        seat_id = SeatID(UUID(data['seat_id']))
        with db.engine.connect() as connection:
            persisted_state = connection.scalar(
                select(DbSeat.blocked).filter_by(id=seat_id)
            )
        assert persisted_state is not None
        self.persisted_states.append(persisted_state)


def test_block_and_unblock_free_seat(
    admin_app,
    category,
    make_area,
    make_seat,
    management_initiator,
    monkeypatch,
):
    area = make_area()
    seat = make_seat(area, category)
    recording_log = RecordingLog()
    monkeypatch.setattr(service, 'log', recording_log)

    block_result = service.set_seat_blocked(
        area.id, seat.id, True, management_initiator
    )

    assert block_result.unwrap() is True
    assert _get_blocked(seat.id) is True
    assert recording_log.entries == [
        (
            'Seat blocked',
            {
                'seating_area_id': str(area.id),
                'seat_id': str(seat.id),
                'seat_label': seat.label,
                'initiator_id': str(management_initiator.id),
                'initiator_screen_name': management_initiator.screen_name,
            },
        )
    ]
    assert recording_log.persisted_states == [True]

    unblock_result = service.set_seat_blocked(
        area.id, seat.id, False, management_initiator
    )

    assert unblock_result.unwrap() is True
    assert _get_blocked(seat.id) is False
    assert [event for event, _ in recording_log.entries] == [
        'Seat blocked',
        'Seat unblocked',
    ]
    assert recording_log.persisted_states == [True, False]


def test_block_and_unblock_are_idempotent_without_duplicate_logs(
    admin_app,
    category,
    make_area,
    make_seat,
    management_initiator,
    monkeypatch,
):
    area = make_area()
    seat = make_seat(area, category)
    recording_log = RecordingLog()
    monkeypatch.setattr(service, 'log', recording_log)

    assert service.set_seat_blocked(
        area.id, seat.id, True, management_initiator
    ).unwrap()
    assert not service.set_seat_blocked(
        area.id, seat.id, True, management_initiator
    ).unwrap()
    assert service.set_seat_blocked(
        area.id, seat.id, False, management_initiator
    ).unwrap()
    assert not service.set_seat_blocked(
        area.id, seat.id, False, management_initiator
    ).unwrap()

    assert [event for event, _ in recording_log.entries] == [
        'Seat blocked',
        'Seat unblocked',
    ]
    assert recording_log.persisted_states == [True, False]


def test_reject_blocking_occupied_seat(
    admin_app,
    category,
    make_area,
    make_seat,
    make_ticket,
    management_initiator,
):
    area = make_area()
    seat = make_seat(area, category)
    make_ticket(category, seat=seat)

    result = service.set_seat_blocked(
        area.id, seat.id, True, management_initiator
    )

    assert isinstance(result.unwrap_err(), SeatOccupiedError)
    assert _get_blocked(seat.id) is False


def test_reject_blocking_group_seat(
    admin_app,
    party,
    category,
    make_area,
    make_group,
    make_seat,
    management_initiator,
):
    area = make_area()
    seat = make_seat(area, category)
    make_group(party, category, [seat])

    result = service.set_seat_blocked(
        area.id, seat.id, True, management_initiator
    )

    assert isinstance(result.unwrap_err(), SeatChangeDeniedForGroupSeatError)
    assert _get_blocked(seat.id) is False


def test_unblock_anomalous_occupied_group_seat(
    admin_app,
    party,
    category,
    make_area,
    make_group,
    make_seat,
    make_ticket,
    management_initiator,
):
    area = make_area()
    seat = make_seat(area, category)
    make_ticket(category, seat=seat)
    make_group(party, category, [seat])
    db.session.get(DbSeat, seat.id).blocked = True
    db.session.commit()

    result = service.set_seat_blocked(
        area.id, seat.id, False, management_initiator
    )

    assert result.unwrap() is True
    assert _get_blocked(seat.id) is False


def test_reject_unknown_seat(admin_app, make_area, management_initiator):
    area = make_area()
    unknown_seat_id = SeatID(generate_uuid())

    result = service.set_seat_blocked(
        area.id, unknown_seat_id, True, management_initiator
    )

    assert isinstance(result.unwrap_err(), SeatNotFoundError)
    assert db.session.scalar(db.select(db.literal(1))) == 1


def test_reject_seat_from_wrong_area(
    admin_app,
    category,
    make_area,
    make_seat,
    management_initiator,
):
    area = make_area()
    other_area = make_area()
    seat = make_seat(area, category)

    result = service.set_seat_blocked(
        other_area.id, seat.id, True, management_initiator
    )

    assert isinstance(result.unwrap_err(), SeatOutsideAreaError)
    assert _get_blocked(seat.id) is False


def test_commit_failure_rolls_back_block_and_keeps_session_usable(
    admin_app,
    category,
    make_area,
    make_seat,
    management_initiator,
    monkeypatch,
):
    area = make_area()
    seat = make_seat(area, category)

    def fail_commit():
        raise RuntimeError('injected commit failure')

    with monkeypatch.context() as context:
        context.setattr(db.session, 'commit', fail_commit)
        with pytest.raises(RuntimeError, match='injected commit failure'):
            service.set_seat_blocked(
                area.id, seat.id, True, management_initiator
            )

    assert _get_blocked(seat.id) is False
    assert db.session.scalar(db.select(db.literal(1))) == 1


def _get_blocked(seat_id: SeatID) -> bool:
    db.session.expire_all()
    db_seat = db.session.get(DbSeat, seat_id)
    assert db_seat is not None
    return db_seat.blocked
