"""
:Copyright: 2026 Y0GI
:License: Revised BSD (see `LICENSE` file for details)
"""

import csv
from io import StringIO
from types import SimpleNamespace

import pytest
from flask import g
from werkzeug.exceptions import Forbidden

from byceps.config.models import AppMode
from byceps.services.chair_optout.blueprints.admin import views as admin_views
from byceps.services.chair_optout.blueprints.site import views as site_views
from byceps.services.chair_optout.models import (
    ChairInformationSummary,
    ChairOptoutReportEntry,
)
from byceps.util import views as util_views

from tests.helpers import generate_uuid


class StubUser:
    def __init__(self, *, permissions=(), authenticated=True, id=None):
        self.permissions = frozenset(permissions)
        self.authenticated = authenticated
        self.id = id

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions


def _make_ticket(
    ticket_id,
    code,
    user_id,
    *,
    party_id='party-1',
    has_seat=True,
    revoked=False,
):
    occupied_seat = SimpleNamespace(label='A-1') if has_seat else None
    return SimpleNamespace(
        id=ticket_id,
        code=code,
        party_id=party_id,
        used_by_id=user_id,
        occupied_seat=occupied_seat,
        revoked=revoked,
    )


def _make_report_entry(
    ticket_code,
    brings_own_chair,
    *,
    has_seat=True,
):
    return ChairOptoutReportEntry(
        ticket_id=generate_uuid(),
        full_name='Alice Example',
        screen_name='alice',
        ticket_code=ticket_code,
        seat_label='A-1' if has_seat else None,
        has_seat=has_seat,
        brings_own_chair=brings_own_chair,
    )


def _unwrap(function):
    while hasattr(function, '__wrapped__'):
        function = function.__wrapped__
    return function


def test_site_index_requires_login(app, monkeypatch):
    with app.test_request_context('/'):
        g.user = SimpleNamespace(authenticated=False)
        g.app_mode = AppMode.site

        monkeypatch.setattr(
            util_views, 'flash_notice', lambda *args, **kwargs: None
        )
        monkeypatch.setattr(
            util_views, 'redirect_to', lambda *args, **kwargs: 'redirected'
        )

        assert site_views.index() == 'redirected'


def test_site_index_rejects_user_without_current_ticket(app, monkeypatch):
    with app.test_request_context('/'):
        g.user = StubUser(id=generate_uuid())
        g.party = SimpleNamespace(id='party-1')
        monkeypatch.setattr(
            site_views.ticket_service,
            'get_tickets_used_by_user',
            lambda *_: [],
        )

        with pytest.raises(Forbidden):
            _unwrap(site_views.index)()


def test_site_index_builds_independent_forms_for_current_tickets(
    app, monkeypatch
):
    app.config['LOCALE'] = 'en'
    user_id = generate_uuid()
    own_ticket = _make_ticket(generate_uuid(), 'T-1', user_id)
    provided_ticket = _make_ticket(
        generate_uuid(), 'T-2', user_id, has_seat=False
    )
    optout = SimpleNamespace(brings_own_chair=True)

    with app.test_request_context('/'):
        g.user = StubUser(id=user_id)
        g.party = SimpleNamespace(id='party-1')
        monkeypatch.setattr(
            site_views.ticket_service,
            'get_tickets_used_by_user',
            lambda *_: [own_ticket, provided_ticket],
        )
        monkeypatch.setattr(
            site_views.chair_optout_service,
            'get_current_optouts_for_tickets',
            lambda _: {own_ticket.id: optout},
        )

        context = _unwrap(site_views.index)()

    first, second = context['ticket_information']
    assert first['ticket'] == own_ticket
    assert first['brings_own_chair'] is True
    assert first['form'].choice.data == 'own'
    assert second['ticket'] == provided_ticket
    assert second['brings_own_chair'] is None
    assert second['form'].choice.data is None


@pytest.mark.parametrize(
    ('submitted_choice', 'expected_value'),
    [('own', True), ('provided', False)],
)
def test_site_update_stores_explicit_choice(
    app, monkeypatch, submitted_choice, expected_value
):
    app.config['LOCALE'] = 'en'
    user_id = generate_uuid()
    ticket_id = generate_uuid()
    ticket = _make_ticket(ticket_id, 'T-1', user_id)
    calls = []

    with app.test_request_context(
        '/',
        method='POST',
        data={f'{ticket_id}-choice': submitted_choice},
    ):
        g.user = StubUser(id=user_id)
        g.party = SimpleNamespace(id='party-1')
        monkeypatch.setattr(
            site_views.ticket_service, 'find_ticket', lambda *_: ticket
        )
        monkeypatch.setattr(
            site_views.chair_optout_service,
            'set_optout',
            lambda *args: calls.append(args),
        )
        monkeypatch.setattr(
            site_views, 'flash_success', lambda *args, **kwargs: None
        )
        monkeypatch.setattr(
            site_views, 'redirect_to', lambda *args, **kwargs: 'redirected'
        )

        result = site_views.update(ticket_id)

    assert result == 'redirected'
    assert calls == [('party-1', ticket_id, user_id, expected_value)]


def test_site_update_allows_ticket_without_seat(app, monkeypatch):
    app.config['LOCALE'] = 'en'
    user_id = generate_uuid()
    ticket_id = generate_uuid()
    ticket = _make_ticket(ticket_id, 'T-1', user_id, has_seat=False)
    calls = []

    with app.test_request_context(
        '/', method='POST', data={f'{ticket_id}-choice': 'provided'}
    ):
        g.user = StubUser(id=user_id)
        g.party = SimpleNamespace(id='party-1')
        monkeypatch.setattr(
            site_views.ticket_service, 'find_ticket', lambda *_: ticket
        )
        monkeypatch.setattr(
            site_views.chair_optout_service,
            'set_optout',
            lambda *args: calls.append(args),
        )
        monkeypatch.setattr(
            site_views, 'flash_success', lambda *args, **kwargs: None
        )
        monkeypatch.setattr(
            site_views, 'redirect_to', lambda *args, **kwargs: 'redirected'
        )

        result = site_views.update(ticket_id)

    assert result == 'redirected'
    assert calls == [('party-1', ticket_id, user_id, False)]


@pytest.mark.parametrize(
    'ticket_overrides',
    [
        {'used_by_id': generate_uuid()},
        {'party_id': 'party-2'},
        {'revoked': True},
    ],
)
def test_site_update_rejects_ineligible_ticket(
    app, monkeypatch, ticket_overrides
):
    user_id = generate_uuid()
    ticket_id = generate_uuid()
    ticket = _make_ticket(ticket_id, 'T-1', user_id)
    for key, value in ticket_overrides.items():
        setattr(ticket, key, value)

    with app.test_request_context(
        '/', method='POST', data={f'{ticket_id}-choice': 'own'}
    ):
        g.user = StubUser(id=user_id)
        g.party = SimpleNamespace(id='party-1')
        monkeypatch.setattr(
            site_views.ticket_service, 'find_ticket', lambda *_: ticket
        )

        with pytest.raises(Forbidden):
            site_views.update(ticket_id)


@pytest.mark.parametrize(
    'relationship_field',
    ['owned_by_id', 'seat_managed_by_id', 'user_managed_by_id'],
)
def test_site_update_rejects_non_participant_relationships(
    app, monkeypatch, relationship_field
):
    app.config['LOCALE'] = 'en'
    user_id = generate_uuid()
    ticket_id = generate_uuid()
    ticket = _make_ticket(ticket_id, 'T-1', generate_uuid())
    setattr(ticket, relationship_field, user_id)

    with app.test_request_context(
        '/', method='POST', data={f'{ticket_id}-choice': 'own'}
    ):
        g.user = StubUser(id=user_id)
        g.party = SimpleNamespace(id='party-1')
        monkeypatch.setattr(
            site_views.ticket_service, 'find_ticket', lambda *_: ticket
        )

        with pytest.raises(Forbidden):
            site_views.update(ticket_id)


def test_admin_views_require_seating_view(app):
    with app.test_request_context('/'):
        g.user = StubUser(permissions=())

        with pytest.raises(Forbidden):
            admin_views.index('party-1')
        with pytest.raises(Forbidden):
            admin_views.chair_information('party-1')
        with pytest.raises(Forbidden):
            admin_views.export_as_csv('party-1')


def test_admin_overview_uses_all_areas_and_valid_own_chair_ids(
    app, monkeypatch
):
    entries = [
        _make_report_entry('T-1', True),
        _make_report_entry('T-2', False),
        _make_report_entry('T-3', None, has_seat=False),
    ]
    areas = [SimpleNamespace(id='area-1'), SimpleNamespace(id='area-2')]

    with app.test_request_context('/'):
        monkeypatch.setattr(
            admin_views.party_service,
            'find_party',
            lambda *_: SimpleNamespace(id='party-1'),
        )
        monkeypatch.setattr(
            admin_views.chair_optout_service,
            'get_report_entries_for_party',
            lambda *_: entries,
        )
        monkeypatch.setattr(
            admin_views.chair_optout_service,
            'summarize_report_entries',
            lambda *_: ChairInformationSummary(
                brings_own_chair=1,
                needs_provided_chair=1,
                not_specified=1,
                no_seat=1,
            ),
        )
        monkeypatch.setattr(
            admin_views.seating_area_service,
            'get_areas_for_party',
            lambda *_: areas,
        )
        monkeypatch.setattr(
            admin_views.seat_service,
            'get_area_seats',
            lambda area_id: [f'seat-{area_id}'],
        )

        context = _unwrap(admin_views.chair_information)('party-1')

    assert context['areas_with_seats'] == [
        (areas[0], ['seat-area-1']),
        (areas[1], ['seat-area-2']),
    ]
    assert context['own_chair_ticket_ids'] == {entries[0].ticket_id}


def test_admin_export_contains_all_states_and_ticket_without_seat(
    app, monkeypatch
):
    entries = [
        _make_report_entry('T-100', True),
        _make_report_entry('T-101', False),
        _make_report_entry('T-102', None, has_seat=False),
    ]

    with app.test_request_context('/'):
        g.user = StubUser(permissions=('seating.view',))
        monkeypatch.setattr(
            admin_views.party_service,
            'find_party',
            lambda *_: SimpleNamespace(id='party-1'),
        )
        monkeypatch.setattr(
            admin_views.chair_optout_service,
            'get_report_entries_for_party',
            lambda *_: entries,
        )

        response = admin_views.export_as_csv('party-1')

    rows = list(csv.reader(StringIO(response.get_data(as_text=True))))
    assert rows[0] == [
        'Name',
        'Nickname',
        'Ticket number',
        'Seat label',
        'Chair information',
    ]
    assert rows[1][-1] == 'Brings own chair'
    assert rows[2][-1] == 'Needs a provided chair'
    assert rows[3][3:] == ['no seat', 'Not specified yet']
