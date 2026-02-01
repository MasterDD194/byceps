"""
:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID, uuid4
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from byceps.services.seating.models import SeatID
from byceps.services.ticketing import ticket_seat_management_service
from byceps.services.ticketing.models.ticket import TicketID


@dataclass
class FakeTicket:
    id: TicketID
    category_id: UUID
    occupied_seat_id: SeatID | None
    code: str
    revoked: bool = False
    bundle_id: UUID | None = None

    @property
    def belongs_to_bundle(self) -> bool:
        return self.bundle_id is not None


@dataclass(frozen=True)
class FakeSeat:
    id: SeatID
    category_id: UUID
    label: str


def test_swap_seats_swaps_and_commits_once():
    ticket_a_id = TicketID(uuid4())
    ticket_b_id = TicketID(uuid4())
    seat_a_id = SeatID(uuid4())
    seat_b_id = SeatID(uuid4())
    category_a = uuid4()
    category_b = uuid4()

    ticket_a = FakeTicket(ticket_a_id, category_a, seat_a_id, code='AAA')
    ticket_b = FakeTicket(ticket_b_id, category_b, seat_b_id, code='BBB')
    seat_a = FakeSeat(seat_a_id, category_b, 'A1')
    seat_b = FakeSeat(seat_b_id, category_a, 'B1')

    db_session = MagicMock()
    db_session.flush = MagicMock()
    db_session.commit = MagicMock()
    db_session.rollback = MagicMock()
    db_session.add = MagicMock()

    with (
        patch(
            'byceps.services.ticketing.ticket_seat_management_service.db.session',
            db_session,
        ),
        patch(
            'byceps.services.ticketing.ticket_seat_management_service.ticket_service.get_ticket',
            side_effect=[ticket_a, ticket_b],
        ),
        patch(
            'byceps.services.ticketing.ticket_seat_management_service.seat_service.get_seat',
            side_effect=[seat_a, seat_b],
        ),
        patch(
            'byceps.services.ticketing.ticket_seat_management_service.seat_group_service.is_seat_part_of_a_group',
            return_value=False,
        ),
        patch(
            'byceps.services.ticketing.ticket_seat_management_service.ticket_log_domain_service.build_occupy_seat_entry',
            return_value=MagicMock(),
        ),
        patch(
            'byceps.services.ticketing.ticket_seat_management_service.ticket_log_service.to_db_entry',
            return_value=MagicMock(),
        ),
    ):
        initiator = SimpleNamespace(id=uuid4())

        actual = ticket_seat_management_service.swap_seats(
            ticket_a_id, ticket_b_id, initiator
        )

    assert actual.is_ok()
    assert ticket_a.occupied_seat_id == seat_b_id
    assert ticket_b.occupied_seat_id == seat_a_id
    db_session.commit.assert_called_once()


def test_swap_seats_rolls_back_on_integrity_error():
    ticket_a_id = TicketID(uuid4())
    ticket_b_id = TicketID(uuid4())
    seat_a_id = SeatID(uuid4())
    seat_b_id = SeatID(uuid4())
    category_a = uuid4()
    category_b = uuid4()

    ticket_a = FakeTicket(ticket_a_id, category_a, seat_a_id, code='AAA')
    ticket_b = FakeTicket(ticket_b_id, category_b, seat_b_id, code='BBB')
    seat_a = FakeSeat(seat_a_id, category_b, 'A1')
    seat_b = FakeSeat(seat_b_id, category_a, 'B1')

    db_session = MagicMock()
    db_session.flush = MagicMock()
    db_session.commit = MagicMock(
        side_effect=IntegrityError('stmt', {}, Exception('boom'))
    )
    db_session.rollback = MagicMock()
    db_session.add = MagicMock()

    with (
        patch(
            'byceps.services.ticketing.ticket_seat_management_service.db.session',
            db_session,
        ),
        patch(
            'byceps.services.ticketing.ticket_seat_management_service.ticket_service.get_ticket',
            side_effect=[ticket_a, ticket_b],
        ),
        patch(
            'byceps.services.ticketing.ticket_seat_management_service.seat_service.get_seat',
            side_effect=[seat_a, seat_b],
        ),
        patch(
            'byceps.services.ticketing.ticket_seat_management_service.seat_group_service.is_seat_part_of_a_group',
            return_value=False,
        ),
        patch(
            'byceps.services.ticketing.ticket_seat_management_service.ticket_log_domain_service.build_occupy_seat_entry',
            return_value=MagicMock(),
        ),
        patch(
            'byceps.services.ticketing.ticket_seat_management_service.ticket_log_service.to_db_entry',
            return_value=MagicMock(),
        ),
    ):
        initiator = SimpleNamespace(id=uuid4())

        with pytest.raises(IntegrityError):
            ticket_seat_management_service.swap_seats(
                ticket_a_id, ticket_b_id, initiator
            )

    db_session.rollback.assert_called_once()


def test_swap_seats_returns_error_if_ticket_has_no_seat():
    ticket_a_id = TicketID(uuid4())
    ticket_b_id = TicketID(uuid4())
    seat_b_id = SeatID(uuid4())
    category_a = uuid4()
    category_b = uuid4()

    ticket_a = FakeTicket(ticket_a_id, category_a, None, code='AAA')
    ticket_b = FakeTicket(ticket_b_id, category_b, seat_b_id, code='BBB')

    with patch(
        'byceps.services.ticketing.ticket_seat_management_service.ticket_service.get_ticket',
        side_effect=[ticket_a, ticket_b],
    ):
        initiator = SimpleNamespace(id=uuid4())

        actual = ticket_seat_management_service.swap_seats(
            ticket_a_id, ticket_b_id, initiator
        )

    assert actual.is_err()
    assert actual.unwrap_err().message == 'Ticket does not occupy a seat.'
