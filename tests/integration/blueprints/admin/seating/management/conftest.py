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

from tests.helpers import generate_token, log_in_user


_UNSET = object()


@pytest.fixture(scope='package')
def management_admin(make_admin):
    admin = make_admin({'admin.access', 'seating.administrate'})
    log_in_user(admin.id)
    return admin


@pytest.fixture(scope='package')
def management_admin_client(make_client, admin_app, management_admin):
    return make_client(admin_app, user_id=management_admin.id)


@pytest.fixture(scope='package')
def seating_viewer(make_admin):
    viewer = make_admin({'admin.access', 'seating.view'})
    log_in_user(viewer.id)
    return viewer


@pytest.fixture(scope='package')
def seating_viewer_client(make_client, admin_app, seating_viewer):
    return make_client(admin_app, user_id=seating_viewer.id)


@pytest.fixture(scope='package')
def management_category(make_ticket_category, party):
    return make_ticket_category(party.id, generate_token())


@pytest.fixture(scope='package')
def management_ticket_owner(make_user):
    return make_user()


@pytest.fixture()
def make_management_area(party):
    def _make_area(*, for_party=party):
        token = generate_token()
        return seating_area_service.create_area(
            for_party.id,
            token,
            token,
            image_filename='plan.png',
            image_width=640,
            image_height=480,
        )

    return _make_area


@pytest.fixture()
def make_management_seat():
    coordinate = count(20, 24)

    def _make_seat(area, category, *, label=_UNSET, type_=None):
        return seat_service.create_seat(
            area.id,
            next(coordinate),
            next(coordinate),
            category.id,
            label=generate_token() if label is _UNSET else label,
            type_=type_,
        )

    return _make_seat


@pytest.fixture()
def make_management_ticket(management_ticket_owner):
    def _make_ticket(category, *, seat=None, user=management_ticket_owner):
        ticket = ticket_creation_service.create_ticket(
            category, management_ticket_owner, user=user
        )
        if seat is not None:
            result = ticket_seat_management_service.occupy_seat(
                ticket.id, seat.id, management_ticket_owner
            )
            assert result.is_ok()
        return ticket

    return _make_ticket


@pytest.fixture()
def make_management_group():
    def _make_group(party, category, seats):
        return seat_group_service.create_group(
            party.id, category.id, generate_token(), seats
        ).unwrap()

    return _make_group
