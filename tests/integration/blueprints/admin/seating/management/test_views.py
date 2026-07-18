"""
:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from types import SimpleNamespace
from uuid import UUID

from byceps.database import db
from byceps.services.party import party_setting_service
from byceps.services.seating.dbmodels.seat import DbSeat
from byceps.services.seating.management import service
from byceps.services.seating.management.blueprints.admin import views
from byceps.services.site import site_service
from byceps.services.ticketing.dbmodels.ticket import DbTicket

from tests.helpers import generate_token, generate_uuid


BASE_URL = 'http://admin.acmecon.test'


def test_management_routes_require_administrate_permission(
    seating_viewer_client,
    management_category,
    make_management_area,
    make_management_seat,
):
    area = make_management_area()
    seat = make_management_seat(area, management_category)
    routes = [
        ('get', f'/seating/management/for_party/{area.party_id}', None),
        ('get', f'/seating/management/areas/{area.id}', None),
        (
            'post',
            f'/seating/management/areas/{area.id}/move',
            {'source_seat_id': str(seat.id), 'target_seat_id': str(seat.id)},
        ),
        (
            'post',
            f'/seating/management/areas/{area.id}/swap',
            {'source_seat_id': str(seat.id), 'target_seat_id': str(seat.id)},
        ),
        (
            'post',
            f'/seating/management/areas/{area.id}/block',
            {'seat_id': str(seat.id)},
        ),
        (
            'post',
            f'/seating/management/areas/{area.id}/unblock',
            {'seat_id': str(seat.id)},
        ),
    ]

    for method, path, data in routes:
        response = getattr(seating_viewer_client, method)(
            BASE_URL + path, data=data
        )
        assert response.status_code == 403


def test_administrate_permission_does_not_require_view_permission(
    management_admin_client, party, make_management_area
):
    area = make_management_area()

    index_response = management_admin_client.get(
        f'{BASE_URL}/seating/management/for_party/{party.id}'
    )
    area_response = management_admin_client.get(
        f'{BASE_URL}/seating/management/areas/{area.id}'
    )

    assert index_response.status_code == 200
    assert area_response.status_code == 200


def test_navigation_entry_uses_administrate_permission(
    management_admin_client, seating_viewer_client, party
):
    management_url = f'/seating/management/for_party/{party.id}'

    admin_response = management_admin_client.get(BASE_URL + management_url)
    viewer_response = seating_viewer_client.get(
        f'{BASE_URL}/seating/{party.id}'
    )

    assert management_url in admin_response.get_data(as_text=True)
    assert management_url not in viewer_response.get_data(as_text=True)


def test_unknown_party_returns_404(management_admin_client):
    response = management_admin_client.get(
        f'{BASE_URL}/seating/management/for_party/unknown-{generate_token()}'
    )

    assert response.status_code == 404


def test_unknown_area_returns_404(management_admin_client):
    response = management_admin_client.get(
        f'{BASE_URL}/seating/management/areas/{generate_uuid()}'
    )

    assert response.status_code == 404


def test_seat_from_different_area_returns_404(
    management_admin_client,
    management_category,
    make_management_area,
    make_management_seat,
):
    area = make_management_area()
    other_area = make_management_area()
    other_seat = make_management_seat(other_area, management_category)

    response = management_admin_client.post(
        f'{BASE_URL}/seating/management/areas/{area.id}/block',
        data={'seat_id': str(other_seat.id)},
    )

    assert response.status_code == 404


def test_party_area_list_renders(
    management_admin_client, party, make_management_area
):
    area1 = make_management_area()
    area2 = make_management_area()

    response = management_admin_client.get(
        f'{BASE_URL}/seating/management/for_party/{party.id}'
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert area1.title in html
    assert area2.title in html
    assert f'/seating/management/areas/{area1.id}' in html


def test_area_view_renders_graphical_states_and_accessible_fallback(
    management_admin_client,
    management_admin,
    management_ticket_owner,
    party,
    management_category,
    make_management_area,
    make_management_group,
    make_management_seat,
    make_management_ticket,
):
    area = make_management_area()
    free_seat = make_management_seat(
        area, management_category, label='Free', type_='vip'
    )
    occupied_seat = make_management_seat(
        area, management_category, label='Occupied'
    )
    owner_only_seat = make_management_seat(
        area, management_category, label='Owner only'
    )
    blocked_seat = make_management_seat(
        area, management_category, label='Blocked'
    )
    group_seat = make_management_seat(area, management_category, label='Group')
    make_management_ticket(management_category, seat=occupied_seat)
    make_management_ticket(management_category, seat=owner_only_seat, user=None)
    service.set_seat_blocked(
        area.id, blocked_seat.id, True, management_admin
    ).unwrap()
    make_management_group(party, management_category, [group_seat])

    response = management_admin_client.get(
        f'{BASE_URL}/seating/management/areas/{area.id}'
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    for seat in (
        free_seat,
        occupied_seat,
        owner_only_seat,
        blocked_seat,
        group_seat,
    ):
        assert f'data-seat-id="{seat.id}"' in html
    assert 'seat-management-seat--free' in html
    assert 'seat-management-seat--occupied' in html
    assert 'seat-management-seat--blocked' in html
    assert 'seat-management-seat--group' in html
    assert 'seat-type--vip' in html
    assert f'data-occupier-name="{management_ticket_owner.screen_name}"' in html
    assert (
        f'data-occupier-avatar="{management_ticket_owner.avatar_url}"' in html
    )
    owner_only_markup = html.split(f'data-seat-id="{owner_only_seat.id}"', 1)[
        1
    ].split('</button>', 1)[0]
    assert 'data-occupier-name' not in owner_only_markup
    assert 'data-occupier-avatar' not in owner_only_markup
    assert html.count('id="seat-management-tooltip"') == 1
    assert (
        'id="seat-management-participant-search" '
        'class="seat-management-participant-search" hidden'
    ) in html
    assert (
        'for="seat-management-participant-search-input" class="form-label"'
        in html
    )
    assert 'id="seat-management-participant-search-input" type="search"' in html
    assert 'data-search-seat-label="Sitzplatz"' in html
    assert (
        'data-search-no-results="Kein passender Teilnehmer gefunden."' in html
    )
    assert '<button' in html
    assert 'type="button"' in html
    assert html.count('aria-pressed="false"') == 5
    assert html.count('\n          disabled\n') == 5
    assert (
        'id="seat-management-reset" type="button" '
        'class="button is-compact" disabled'
    ) in html
    assert 'aria-live="polite"' in html
    assert 'name="source_seat_id"' in html
    assert 'name="target_seat_id"' in html
    assert 'name="seat_id"' in html
    for field_id in (
        'move-source-seat-id',
        'move-target-seat-id',
        'swap-source-seat-id',
        'swap-target-seat-id',
        'block-seat-id',
        'unblock-seat-id',
    ):
        assert f'for="{field_id}"' in html
        assert f'id="{field_id}"' in html
    assert 'data-ticket-id' not in html


def test_area_view_loads_primary_site_seating_stylesheet(
    management_admin_client,
    party,
    make_management_area,
):
    party_setting_service.create_or_update_setting(
        party.id, 'primary_party_site_id', 'totalverplant'
    )
    area = make_management_area()

    try:
        response = management_admin_client.get(
            f'{BASE_URL}/seating/management/areas/{area.id}'
        )

        assert (
            '/static_sites/totalverplant/style/seating.css'
            in response.get_data(as_text=True)
        )
    finally:
        party_setting_service.remove_setting(party.id, 'primary_party_site_id')


def test_area_view_loads_associated_site_seating_stylesheet(
    management_admin_client,
    party,
    make_management_area,
    monkeypatch,
    tmp_path,
):
    site_id = 'custom-site'
    stylesheet_path = tmp_path / site_id / 'static/style/seating.css'
    stylesheet_path.parent.mkdir(parents=True)
    stylesheet_path.touch()
    monkeypatch.setattr(views, 'SITES_PATH', tmp_path)
    monkeypatch.setattr(
        site_service,
        'get_all_sites',
        lambda: [SimpleNamespace(id=site_id, party_id=party.id)],
    )
    area = make_management_area()

    response = management_admin_client.get(
        f'{BASE_URL}/seating/management/areas/{area.id}'
    )

    assert f'/static_sites/{site_id}/style/seating.css' in response.get_data(
        as_text=True
    )


def test_area_view_does_not_guess_between_site_stylesheets(
    management_admin_client,
    party,
    make_management_area,
    monkeypatch,
    tmp_path,
):
    site_ids = ['custom-site-1', 'custom-site-2']
    for site_id in site_ids:
        stylesheet_path = tmp_path / site_id / 'static/style/seating.css'
        stylesheet_path.parent.mkdir(parents=True)
        stylesheet_path.touch()
    monkeypatch.setattr(views, 'SITES_PATH', tmp_path)
    monkeypatch.setattr(
        site_service,
        'get_all_sites',
        lambda: [
            SimpleNamespace(id=site_id, party_id=party.id)
            for site_id in site_ids
        ],
    )
    area = make_management_area()

    response = management_admin_client.get(
        f'{BASE_URL}/seating/management/areas/{area.id}'
    )
    html = response.get_data(as_text=True)

    assert all(f'/static_sites/{site_id}/' not in html for site_id in site_ids)


def test_area_view_ignores_noncanonical_site_stylesheet_path(
    management_admin_client,
    party,
    make_management_area,
):
    party_setting_service.create_or_update_setting(
        party.id, 'primary_party_site_id', '../sites/totalverplant'
    )
    area = make_management_area()

    try:
        response = management_admin_client.get(
            f'{BASE_URL}/seating/management/areas/{area.id}'
        )

        assert '/static_sites/../sites/totalverplant/' not in response.get_data(
            as_text=True
        )
    finally:
        party_setting_service.remove_setting(party.id, 'primary_party_site_id')


def test_area_view_sorts_dropdown_choices_naturally(
    management_admin_client,
    management_category,
    make_management_area,
    make_management_seat,
):
    area = make_management_area()
    for label in (
        'A10',
        'A2',
        'A1',
        'Reihe A Platz 10',
        'Reihe A Platz 2',
        'Reihe A Platz 1',
        'A' + '9' * 4301,
    ):
        make_management_seat(area, management_category, label=label)
    unlabeled_seats = [
        make_management_seat(area, management_category, label=label)
        for label in ('', '   ', None)
    ]

    response = management_admin_client.get(
        f'{BASE_URL}/seating/management/areas/{area.id}'
    )
    html = response.get_data(as_text=True)
    block_select = html.split('id="block-seat-id"', 1)[1].split('</select>', 1)[
        0
    ]

    assert block_select.index('>A1<') < block_select.index('>A2<')
    assert block_select.index('>A2<') < block_select.index('>A10<')
    assert block_select.index('>A10<') < block_select.index('>A999')
    assert block_select.index('>Reihe A Platz 1<') < block_select.index(
        '>Reihe A Platz 2<'
    )
    assert block_select.index('>Reihe A Platz 2<') < block_select.index(
        '>Reihe A Platz 10<'
    )
    for seat in unlabeled_seats:
        assert block_select.index('>A999') < block_select.index(f'>{seat.id}<')


def test_move_uses_prg_and_ignores_extra_client_fields(
    management_admin_client,
    management_category,
    make_management_area,
    make_management_seat,
    make_management_ticket,
):
    area = make_management_area()
    source_seat = make_management_seat(area, management_category)
    target_seat = make_management_seat(area, management_category)
    unrelated_seat = make_management_seat(area, management_category)
    ticket = make_management_ticket(management_category, seat=source_seat)
    unrelated_ticket = make_management_ticket(
        management_category, seat=unrelated_seat
    )

    response = management_admin_client.post(
        f'{BASE_URL}/seating/management/areas/{area.id}/move',
        data={
            'source_seat_id': str(source_seat.id),
            'target_seat_id': str(target_seat.id),
            'ticket_id': str(unrelated_ticket.id),
            'user_id': str(generate_uuid()),
            'mode': 'swap',
            'category': 'manipulated',
            'occupancy': 'manipulated',
            'bundle': 'manipulated',
            'group': 'manipulated',
            'blocked': 'true',
        },
    )

    assert response.status_code == 302
    assert response.location.endswith(f'/seating/management/areas/{area.id}')
    assert _get_occupied_seat_id(ticket.id) == target_seat.id
    assert _get_occupied_seat_id(unrelated_ticket.id) == unrelated_seat.id

    follow_response = management_admin_client.get(response.location)
    assert 'Der Sitzplatzinhaber wurde verschoben.' in follow_response.get_data(
        as_text=True
    )


def test_swap_uses_prg_and_translated_success_flash(
    management_admin_client,
    management_category,
    make_management_area,
    make_management_seat,
    make_management_ticket,
):
    area = make_management_area()
    source_seat = make_management_seat(area, management_category)
    target_seat = make_management_seat(area, management_category)
    source_ticket = make_management_ticket(
        management_category, seat=source_seat
    )
    target_ticket = make_management_ticket(
        management_category, seat=target_seat
    )

    response = management_admin_client.post(
        f'{BASE_URL}/seating/management/areas/{area.id}/swap',
        data={
            'source_seat_id': str(source_seat.id),
            'target_seat_id': str(target_seat.id),
        },
    )

    assert response.status_code == 302
    assert _get_occupied_seat_id(source_ticket.id) == target_seat.id
    assert _get_occupied_seat_id(target_ticket.id) == source_seat.id
    follow_response = management_admin_client.get(response.location)
    assert 'Die Sitzplatzinhaber wurden getauscht.' in (
        follow_response.get_data(as_text=True)
    )


def test_block_and_unblock_use_prg(
    management_admin_client,
    management_category,
    make_management_area,
    make_management_seat,
):
    area = make_management_area()
    seat = make_management_seat(area, management_category)

    block_response = management_admin_client.post(
        f'{BASE_URL}/seating/management/areas/{area.id}/block',
        data={'seat_id': str(seat.id)},
    )
    assert block_response.status_code == 302
    assert _get_blocked(seat.id) is True

    unblock_response = management_admin_client.post(
        f'{BASE_URL}/seating/management/areas/{area.id}/unblock',
        data={'seat_id': str(seat.id)},
    )
    assert unblock_response.status_code == 302
    assert _get_blocked(seat.id) is False


def test_blocking_occupied_seat_does_not_release_ticket(
    management_admin_client,
    management_category,
    make_management_area,
    make_management_seat,
    make_management_ticket,
):
    area = make_management_area()
    seat = make_management_seat(area, management_category)
    ticket = make_management_ticket(management_category, seat=seat)

    response = management_admin_client.post(
        f'{BASE_URL}/seating/management/areas/{area.id}/block',
        data={'seat_id': str(seat.id)},
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert _get_occupied_seat_id(ticket.id) == seat.id
    assert _get_blocked(seat.id) is False
    assert (
        'Dieser Sitzplatz ist belegt. Verschiebe das Ticket oder gib den '
        'Sitzplatz separat frei, bevor du ihn sperrst.'
    ) in html


def test_blocking_group_seat_is_rejected(
    management_admin_client,
    party,
    management_category,
    make_management_area,
    make_management_group,
    make_management_seat,
):
    area = make_management_area()
    seat = make_management_seat(area, management_category)
    make_management_group(party, management_category, [seat])

    response = management_admin_client.post(
        f'{BASE_URL}/seating/management/areas/{area.id}/block',
        data={'seat_id': str(seat.id)},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert _get_blocked(seat.id) is False
    assert 'Sitzplätze in einer Sitzplatzgruppe' in response.get_data(
        as_text=True
    )


def test_blocked_target_cannot_be_used_for_move(
    management_admin_client,
    management_admin,
    management_category,
    make_management_area,
    make_management_seat,
    make_management_ticket,
):
    area = make_management_area()
    source_seat = make_management_seat(area, management_category)
    target_seat = make_management_seat(area, management_category)
    ticket = make_management_ticket(management_category, seat=source_seat)
    service.set_seat_blocked(
        area.id, target_seat.id, True, management_admin
    ).unwrap()

    response = management_admin_client.post(
        f'{BASE_URL}/seating/management/areas/{area.id}/move',
        data={
            'source_seat_id': str(source_seat.id),
            'target_seat_id': str(target_seat.id),
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert _get_occupied_seat_id(ticket.id) == source_seat.id
    assert 'Gesperrte Sitzplätze können nicht als Ziel' in (
        response.get_data(as_text=True)
    )


def test_blueprint_local_assets_are_served(management_admin_client):
    css_response = management_admin_client.get(
        f'{BASE_URL}/seating/management/static/style/seating_management.css'
    )
    js_response = management_admin_client.get(
        f'{BASE_URL}/seating/management/static/behavior/seating_management.js'
    )

    assert css_response.status_code == 200
    assert css_response.mimetype == 'text/css'
    assert js_response.status_code == 200
    assert js_response.mimetype in {'text/javascript', 'application/javascript'}
    tooltip_rule = (
        css_response.get_data(as_text=True)
        .split('.seat-management-tooltip {', 1)[1]
        .split('}', 1)[0]
    )
    assert 'pointer-events: none;' in tooltip_rule


def test_german_title_and_actions_render(
    management_admin_client, make_management_area
):
    area = make_management_area()

    response = management_admin_client.get(
        f'{BASE_URL}/seating/management/areas/{area.id}',
        headers={'Accept-Language': 'de'},
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Sitzplatzverwaltung' in html
    assert 'Teilnehmer nach Nickname suchen' in html
    assert 'Kein passender Teilnehmer gefunden.' in html
    assert 'Sitzplatzinhaber verschieben' in html
    assert 'Sitzplatz sperren' in html
    assert 'Sitzplatz entsperren' in html


def _get_occupied_seat_id(ticket_id: UUID):
    db.session.expire_all()
    db_ticket = db.session.get(DbTicket, ticket_id)
    assert db_ticket is not None
    return db_ticket.occupied_seat_id


def _get_blocked(seat_id: UUID) -> bool:
    db.session.expire_all()
    db_seat = db.session.get(DbSeat, seat_id)
    assert db_seat is not None
    return db_seat.blocked
