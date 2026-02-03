"""
:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from byceps.services.seating import seat_service, seating_area_service

# Import models to ensure the corresponding tables are created so
# `Seat.assignment` is available.
import byceps.services.seating.dbmodels.seat_group  # noqa: F401
from byceps.services.ticketing import (
    ticket_creation_service,
    ticket_seat_management_service,
    ticket_service,
)

from tests.helpers import generate_token


BASE_URL = 'http://admin.acmecon.test'


def test_relocate_move_rejects_cross_area_source_seat(
    admin_app,
    seating_admin_client,
    seating_admin,
    party,
    make_ticket_category,
    make_user,
):
    category = make_ticket_category(party.id, generate_token())

    area_a = seating_area_service.create_area(
        party.id, generate_token(), generate_token()
    )
    area_b = seating_area_service.create_area(
        party.id, generate_token(), generate_token()
    )

    seat_a1 = seat_service.create_seat(area_a.id, 0, 1, category.id)
    seat_b1 = seat_service.create_seat(area_b.id, 0, 1, category.id)

    ticket_owner = make_user()
    ticket = ticket_creation_service.create_ticket(category, ticket_owner)

    occupy_result = ticket_seat_management_service.occupy_seat(
        ticket.id, seat_a1.id, seating_admin
    )
    assert occupy_result.is_ok()
    assert ticket.occupied_seat_id == seat_a1.id
    assert ticket_service.find_ticket_occupying_seat(seat_b1.id) is None

    url = f'{BASE_URL}/seating/areas/{area_b.id}/relocate'
    form_data = {
        'mode': 'move',
        'ticket_id': str(ticket.id),
        'source_seat_id': str(seat_a1.id),
        'target_seat_id': str(seat_b1.id),
    }
    response = seating_admin_client.post(url, data=form_data)
    assert response.status_code == 302
    assert response.headers['Location'].endswith(
        f'/seating/areas/{area_b.id}/relocate'
    )

    ticket_after = ticket_service.find_ticket(ticket.id)
    assert ticket_after.occupied_seat_id == seat_a1.id
    assert ticket_service.find_ticket_occupying_seat(seat_b1.id) is None


def test_relocate_move_within_area_succeeds(
    admin_app,
    seating_admin_client,
    seating_admin,
    party,
    make_ticket_category,
    make_user,
):
    category = make_ticket_category(party.id, generate_token())

    area = seating_area_service.create_area(
        party.id, generate_token(), generate_token()
    )

    seat_1 = seat_service.create_seat(area.id, 1, 1, category.id)
    seat_2 = seat_service.create_seat(area.id, 1, 2, category.id)

    ticket_owner = make_user()
    ticket = ticket_creation_service.create_ticket(category, ticket_owner)

    occupy_result = ticket_seat_management_service.occupy_seat(
        ticket.id, seat_1.id, seating_admin
    )
    assert occupy_result.is_ok()
    assert ticket.occupied_seat_id == seat_1.id

    url = f'{BASE_URL}/seating/areas/{area.id}/relocate'
    form_data = {
        'mode': 'move',
        'ticket_id': str(ticket.id),
        'source_seat_id': str(seat_1.id),
        'target_seat_id': str(seat_2.id),
    }
    response = seating_admin_client.post(url, data=form_data)
    assert response.status_code == 302
    assert response.headers['Location'].endswith(
        f'/seating/areas/{area.id}/relocate'
    )

    ticket_after = ticket_service.find_ticket(ticket.id)
    assert ticket_after.occupied_seat_id == seat_2.id
    assert ticket_service.find_ticket_occupying_seat(seat_1.id) is None
