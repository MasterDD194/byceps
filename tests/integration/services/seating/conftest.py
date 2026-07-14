"""
:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from itertools import count

import pytest

from byceps.services.seating import (
    seat_group_service,
    seat_service,
    seating_area_service,
)
from byceps.services.ticketing import (
    ticket_creation_service,
    ticket_seat_management_service,
)

from tests.helpers import generate_token


@pytest.fixture()
def management_initiator(make_user):
    return make_user()


@pytest.fixture()
def ticket_owner(make_user):
    return make_user()


@pytest.fixture()
def category(make_ticket_category, party):
    return make_ticket_category(party.id, generate_token())


@pytest.fixture()
def another_category(make_ticket_category, party):
    return make_ticket_category(party.id, generate_token())


@pytest.fixture()
def another_party(make_party, brand):
    return make_party(brand)


@pytest.fixture()
def make_area(party):
    def _make_area(*, for_party=party):
        token = generate_token()
        return seating_area_service.create_area(for_party.id, token, token)

    return _make_area


@pytest.fixture()
def make_seat():
    coordinate = count()

    def _make_seat(area, category, *, label=None):
        if label is None:
            label = generate_token()

        return seat_service.create_seat(
            area.id,
            next(coordinate),
            next(coordinate),
            category.id,
            label=label,
        )

    return _make_seat


@pytest.fixture()
def make_ticket(ticket_owner):
    def _make_ticket(category, *, seat=None, owner=ticket_owner):
        ticket = ticket_creation_service.create_ticket(category, owner)
        if seat is not None:
            result = ticket_seat_management_service.occupy_seat(
                ticket.id, seat.id, owner
            )
            assert result.is_ok()

        return ticket

    return _make_ticket


@pytest.fixture()
def make_group():
    def _make_group(party, category, seats):
        return seat_group_service.create_group(
            party.id, category.id, generate_token(), seats
        ).unwrap()

    return _make_group
