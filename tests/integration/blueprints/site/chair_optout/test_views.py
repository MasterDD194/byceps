"""
:License: Revised BSD (see `LICENSE` file for details)
"""

import pytest

from flask import url_for
from flask_babel import force_locale, gettext
from sqlalchemy import select
from sqlalchemy.orm import Session

from byceps.database import db
from byceps.services.party.dbmodels import DbParty
from byceps.services.seating import seat_service, seating_area_service
from byceps.services.seating.blueprints.site import views as seating_views
from byceps.services.site.models import SiteID
from byceps.services.ticketing import (
    ticket_creation_service,
    ticket_seat_management_service,
    ticket_user_management_service,
)
from byceps.services.ticketing.dbmodels.ticket import DbTicket
from byceps.services.ticketing.log import ticket_log_service
from byceps.services.ticketing.log.dbmodels import DbTicketLogEntry
from byceps.services.ticketing.models.ticket import ChairSource
from byceps.util.templating import create_site_template_loader

from tests.helpers import (
    generate_token,
    generate_uuid,
    http_client,
    log_in_user,
)


BASE_URL = 'http://www.acmecon.test'


@pytest.fixture(autouse=True)
def enable_ticket_management(admin_app, party):
    db_party = db.session.get(DbParty, party.id)
    previous_value = db_party.ticket_management_enabled
    db_party.ticket_management_enabled = True
    db.session.commit()
    yield
    db_party.ticket_management_enabled = previous_value
    db.session.commit()


@pytest.fixture
def theme_app(make_site_app, site):
    app = make_site_app('www.acmecon.test', site.id)
    app.jinja_loader = create_site_template_loader(SiteID('totalverplant-36'))
    with app.app_context():
        yield app


def test_legacy_index_requires_login(site_app, site):
    with http_client(site_app) as client:
        response = client.get(f'{BASE_URL}/chair_optout/')

    assert response.status_code == 302


@pytest.mark.parametrize('ticket_id_arg', ['own', 'foreign', 'invalid', None])
def test_legacy_index_redirects_with_only_valid_participant_anchor(
    site_app, site, party, make_user, make_ticket_category, ticket_id_arg
):
    participant = make_user(generate_token())
    other_user = make_user(generate_token())
    category = make_ticket_category(party.id, generate_token())
    ticket = ticket_creation_service.create_ticket(
        category, participant, user=participant
    )
    foreign_ticket = ticket_creation_service.create_ticket(
        category, participant, user=other_user
    )
    log_in_user(participant.id)
    query = {
        'own': str(ticket.id),
        'foreign': str(foreign_ticket.id),
        'invalid': 'invalid',
        None: None,
    }[ticket_id_arg]

    with http_client(site_app, user_id=participant.id) as client:
        response = client.get(
            f'{BASE_URL}/chair_optout/',
            query_string={'ticket_id': query} if query else None,
        )
        obsolete_response = client.post(f'{BASE_URL}/chair_optout/{ticket.id}')
        obsolete_index_response = client.post(f'{BASE_URL}/chair_optout/')

    assert response.status_code == 302
    assert response.location.endswith(
        f'/tickets/mine#ticket-{ticket.id}'
        if ticket_id_arg == 'own'
        else '/tickets/mine'
    )
    assert obsolete_response.status_code == 405
    assert obsolete_index_response.status_code == 405


def test_gv36_ticket_controls_offer_only_two_choices(
    theme_app, party, make_user, make_ticket_category
):
    participant = make_user(generate_token())
    category = make_ticket_category(party.id, generate_token())
    ticket = ticket_creation_service.create_ticket(
        category, participant, user=participant
    )
    ticket_seat_management_service.set_chair_source(
        ticket.id, ChairSource.rental, participant
    ).unwrap()
    log_in_user(participant.id)

    with http_client(theme_app, user_id=participant.id) as client:
        response = client.get(f'{BASE_URL}/tickets/mine')

    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert f'id="ticket-{ticket.id}"' in text
    assert ticket.code in text
    assert 'class="bote-page tickets-page"' in text
    assert _translate(theme_app, 'rented') in text
    for source in ['user', 'venue']:
        assert f' href="{_chair_url(theme_app, ticket.id, source)}"' in text
    assert f' href="{_chair_url(theme_app, ticket.id, "rental")}"' not in text
    assert f' href="{_chair_url(theme_app, ticket.id, "unknown")}"' not in text
    assert text.count(' data-action="set-chair-source"') == 2
    assert 'behavior/chair-information.js' in text
    assert 'chair-submit' not in text


def test_current_participant_stores_both_choices_in_core(
    site_app, site, party, make_user, make_ticket_category
):
    participant = make_user(generate_token())
    owner = make_user(generate_token())
    category = make_ticket_category(party.id, generate_token())
    ticket = ticket_creation_service.create_ticket(
        category, owner, user=participant
    )
    log_in_user(participant.id)

    with http_client(site_app, user_id=participant.id) as client:
        for source, expected in [
            ('user', ChairSource.user),
            ('venue', ChairSource.venue),
        ]:
            response = client.post(_chair_url(site_app, ticket.id, source))
            assert response.status_code == 204
            assert _get_persisted_chair_source(ticket.id) is expected

    with Session(db.engine) as session:
        entries = session.scalars(
            select(DbTicketLogEntry)
            .filter_by(ticket_id=ticket.id, event_type='chair-source-set')
            .order_by(DbTicketLogEntry.occurred_at, DbTicketLogEntry.id)
        ).all()
        assert [entry.data for entry in entries] == [
            {'chair_source': source, 'initiator_id': str(participant.id)}
            for source in ['user', 'venue']
        ]


@pytest.mark.parametrize(
    'source', ['invalid', 'own', 'provided', 'unknown', 'rental']
)
def test_invalid_source_preserves_core_answer(
    site_app, site, party, make_user, make_ticket_category, source
):
    participant = make_user(generate_token())
    category = make_ticket_category(party.id, generate_token())
    ticket = ticket_creation_service.create_ticket(
        category, participant, user=participant
    )
    ticket_seat_management_service.set_chair_source(
        ticket.id, ChairSource.user, participant
    ).unwrap()
    entries_before = ticket_log_service.get_entries_for_ticket(ticket.id)
    log_in_user(participant.id)

    with http_client(site_app, user_id=participant.id) as client:
        response = client.post(_chair_url(site_app, ticket.id, source))

    assert response.status_code == 400
    assert _get_persisted_chair_source(ticket.id) is ChairSource.user
    assert (
        ticket_log_service.get_entries_for_ticket(ticket.id) == entries_before
    )


@pytest.mark.parametrize(
    'scenario',
    ['foreign_user', 'foreign_party', 'revoked', 'checked_in', 'disabled'],
)
def test_ineligible_update_is_denied_without_writes(
    theme_app,
    party,
    brand,
    make_party,
    make_user,
    make_ticket_category,
    scenario,
):
    participant = make_user(generate_token())
    other_user = make_user(generate_token())
    ticket_party = make_party(brand) if scenario == 'foreign_party' else party
    category = make_ticket_category(ticket_party.id, generate_token())
    ticket = ticket_creation_service.create_ticket(
        category,
        participant,
        user=other_user if scenario == 'foreign_user' else participant,
    )
    ticket_seat_management_service.set_chair_source(
        ticket.id, ChairSource.venue, participant
    ).unwrap()
    if scenario == 'revoked':
        ticket.revoked = True
    elif scenario == 'checked_in':
        ticket.user_checked_in = True
    elif scenario == 'disabled':
        db.session.get(DbParty, party.id).ticket_management_enabled = False
    db.session.commit()
    entries_before = ticket_log_service.get_entries_for_ticket(ticket.id)
    log_in_user(participant.id)

    with http_client(theme_app, user_id=participant.id) as client:
        response = client.post(_chair_url(theme_app, ticket.id, 'user'))
        tickets_response = client.get(f'{BASE_URL}/tickets/mine')

    assert response.status_code in {403, 404}
    assert _get_persisted_chair_source(ticket.id) is ChairSource.venue
    assert (
        ticket_log_service.get_entries_for_ticket(ticket.id) == entries_before
    )
    assert tickets_response.status_code == 200
    assert ' data-action="set-chair-source"' not in tickets_response.get_data(
        as_text=True
    )


def test_unknown_ticket_is_not_found(site_app, site, make_user):
    participant = make_user(generate_token())
    log_in_user(participant.id)
    with http_client(site_app, user_id=participant.id) as client:
        response = client.post(_chair_url(site_app, generate_uuid(), 'user'))
    assert response.status_code == 404


def test_core_chair_update_requires_login(
    site_app, site, party, make_user, make_ticket_category
):
    participant = make_user(generate_token())
    category = make_ticket_category(party.id, generate_token())
    ticket = ticket_creation_service.create_ticket(
        category, participant, user=participant
    )
    with http_client(site_app) as client:
        response = client.post(_chair_url(site_app, ticket.id, 'user'))
    assert response.status_code == 302
    assert _get_persisted_chair_source(ticket.id) is None
    assert not ticket_log_service.get_entries_for_ticket(ticket.id)


def test_gv36_seating_reminder_tracks_own_ticket_while_managing_others(
    theme_app, party, make_user, make_ticket_category, monkeypatch
):
    participant = make_user(generate_token())
    other_user = make_user(generate_token())
    category = make_ticket_category(party.id, generate_token())
    area = seating_area_service.create_area(
        party.id,
        generate_token(),
        generate_token(),
        image_filename='hall.png',
        image_width=600,
        image_height=400,
    )
    seat_service.create_seat(area.id, 20, 20, category.id)
    own_ticket = ticket_creation_service.create_ticket(
        category, other_user, user=participant
    )
    managed_ticket = ticket_creation_service.create_ticket(
        category, participant, user=other_user
    )
    log_in_user(participant.id)
    monkeypatch.setattr(
        seating_views, '_is_seat_management_enabled', lambda: True
    )
    url = f'{BASE_URL}/seating/areas/{area.slug}/manage_seats'

    with http_client(theme_app, user_id=participant.id) as client:
        pending_response = client.get(url)
        assert (
            client.post(
                _chair_url(theme_app, own_ticket.id, 'venue')
            ).status_code
            == 204
        )
        answered_response = client.get(url)
        ticket_user_management_service.appoint_user(
            own_ticket.id, other_user, other_user
        ).unwrap()
        ticket_user_management_service.appoint_user(
            own_ticket.id, participant, other_user
        ).unwrap()
        reset_response = client.get(url)

    for response in [pending_response, reset_response]:
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert managed_ticket.code in html
        assert 'class="block chair-prompt"' in html
        assert f'/tickets/mine#ticket-{own_ticket.id}' in html
        assert f'/tickets/mine#ticket-{managed_ticket.id}' not in html
    assert answered_response.status_code == 200
    assert 'chair-information-link"' not in answered_response.get_data(
        as_text=True
    )


def test_seat_manager_without_used_ticket_has_no_chair_reminder(
    theme_app, party, make_user, make_ticket_category, monkeypatch
):
    owner = make_user(generate_token())
    participant = make_user(generate_token())
    category = make_ticket_category(party.id, generate_token())
    area = seating_area_service.create_area(
        party.id,
        generate_token(),
        generate_token(),
        image_filename='hall.png',
        image_width=600,
        image_height=400,
    )
    seat_service.create_seat(area.id, 20, 20, category.id)
    ticket = ticket_creation_service.create_ticket(
        category, owner, user=participant
    )
    log_in_user(owner.id)
    monkeypatch.setattr(
        seating_views, '_is_seat_management_enabled', lambda: True
    )
    with http_client(theme_app, user_id=owner.id) as client:
        response = client.get(
            f'{BASE_URL}/seating/areas/{area.slug}/manage_seats'
        )
    assert response.status_code == 200
    assert ticket.code in response.get_data(as_text=True)
    assert 'chair-information-link"' not in response.get_data(as_text=True)


def _get_persisted_chair_source(ticket_id):
    # Requests commit in a separate app-scoped session from these fixtures.
    with Session(db.engine) as session:
        return session.get(DbTicket, ticket_id).chair_source


def _chair_url(app, ticket_id, source):
    with app.test_request_context():
        return url_for(
            'ticketing.set_chair_source',
            ticket_id=ticket_id,
            chair_source=source,
        )


def _translate(app, message: str) -> str:
    with app.test_request_context():
        with force_locale(app.config['LOCALE']):
            return gettext(message)
