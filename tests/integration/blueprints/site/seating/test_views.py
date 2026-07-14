"""
:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from html.parser import HTMLParser
from pathlib import Path
import re
from types import SimpleNamespace

from babel import Locale
from flask import g

from byceps.services.seating import seat_service, seating_area_service
from byceps.services.seating.management import service as management_service
from byceps.services.ticketing import (
    ticket_creation_service,
    ticket_seat_management_service,
)

from tests.helpers import generate_token, generate_uuid, http_client


BASE_URL = 'http://totalverplant.test'
OVERRIDES_PATH = Path('sites/totalverplant/template_overrides')
SEATING_STYLESHEET_PATH = Path('sites/totalverplant/static/style/seating.css')


def test_totalverplant_seating_templates_override_blueprint_templates(
    totalverplant_site_app,
):
    macro_template = totalverplant_site_app.jinja_env.get_template(
        'macros/seating.html'
    )
    legend_template = totalverplant_site_app.jinja_env.get_template(
        'site/seating/_legend.html'
    )

    assert (
        Path(macro_template.filename).resolve()
        == (OVERRIDES_PATH / 'macros/seating.html').resolve()
    )
    assert (
        Path(legend_template.filename).resolve()
        == (OVERRIDES_PATH / 'site/seating/_legend.html').resolve()
    )

    seat_id = generate_uuid()
    seat = SimpleNamespace(
        id=seat_id,
        label='A4',
        area=SimpleNamespace(slug='main-hall'),
    )
    with totalverplant_site_app.test_request_context('/'):
        g.user = SimpleNamespace(locale=None)
        g.locales = [Locale('de')]
        seat_link = str(macro_template.module.render_seat_link(seat))

    assert f'href="/seating/areas/main-hall#seat-{seat_id}"' in seat_link
    assert '>A4</a>' in seat_link


def test_totalverplant_seating_view_renders_blocked_state(
    totalverplant_site_app,
    party,
    make_ticket_category,
    make_user,
):
    category = make_ticket_category(party.id, generate_token())
    area = seating_area_service.create_area(
        party.id,
        generate_token(),
        'Main hall',
        image_filename='plan.png',
        image_width=640,
        image_height=480,
    )
    free_seat = seat_service.create_seat(
        area.id, 50, 20, category.id, label='A1'
    )
    blocked_seat = seat_service.create_seat(
        area.id,
        10,
        40,
        category.id,
        rotation=45,
        label='A2',
        type_='narrow',
    )
    occupied_seat = seat_service.create_seat(
        area.id,
        30,
        60,
        category.id,
        rotation=90,
        label='A3',
        type_='vip',
    )
    ticket_owner = make_user()
    occupier = make_user()
    management_service.set_seat_blocked(
        area.id, blocked_seat.id, True, ticket_owner
    ).unwrap()
    ticket = ticket_creation_service.create_ticket(
        category, ticket_owner, user=occupier
    )
    ticket_seat_management_service.occupy_seat(
        ticket.id, occupied_seat.id, ticket_owner
    ).unwrap()

    with http_client(totalverplant_site_app) as client:
        response = client.get(f'{BASE_URL}/seating/areas/{area.slug}')
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '/static_sites/totalverplant/style/seating.css' in html
    assert html.index(
        'href="/static_sites/totalverplant/style/seating.css"'
    ) < html.index('href="/static/style/seating.css"')

    seat_parser = _SeatHTMLParser()
    seat_parser.feed(html)

    blocked_container, blocked_element = seat_parser.seats[str(blocked_seat.id)]
    assert blocked_container['data-seat-id'] == str(blocked_seat.id)
    assert blocked_container['data-label'] == 'A2 (Gesperrt)'
    assert blocked_container['data-blocked'] == 'true'
    assert blocked_container['style'] == 'left: 10px; top: 40px;'
    assert 'seat-type--narrow' in blocked_element['class'].split()
    assert 'seat--blocked' in blocked_element['class'].split()
    assert blocked_element['style'] == 'transform: rotate(45deg);'

    free_container, free_element = seat_parser.seats[str(free_seat.id)]
    assert free_container['data-seat-id'] == str(free_seat.id)
    assert free_container['data-label'] == 'A1'
    assert 'data-blocked' not in free_container
    assert 'seat--blocked' not in free_element['class'].split()

    occupied_container, occupied_element = seat_parser.seats[
        str(occupied_seat.id)
    ]
    assert occupied_container['data-seat-id'] == str(occupied_seat.id)
    assert occupied_container['data-label'] == 'A3'
    assert occupied_container['data-ticket-id'] == str(ticket.id)
    assert occupied_container['data-occupier-avatar'] == occupier.avatar_url
    assert occupied_container['data-occupier-name'] == occupier.screen_name
    assert occupied_container['style'] == 'left: 30px; top: 60px;'
    assert 'seat-type--vip' in occupied_element['class'].split()
    assert 'seat--occupied' in occupied_element['class'].split()
    assert occupied_element['style'] == 'transform: rotate(90deg);'

    assert seat_parser.order == [
        str(blocked_seat.id),
        str(occupied_seat.id),
        str(free_seat.id),
    ]

    legend_markup = html.split('<small class="seats-legend">', 1)[1].split(
        '</small>', 1
    )[0]
    assert '<div class="seat seat--blocked"></div> Gesperrt' in legend_markup
    assert 'seat--occupied' in legend_markup


def test_totalverplant_blocked_seat_styles_prevent_pointer_selection():
    css = SEATING_STYLESHEET_PATH.read_text()

    parent_rule = _get_css_rule(
        css, r"\.seat-with-tooltip\[data-blocked='true'\]"
    )
    assert 'cursor: not-allowed;' in parent_rule
    assert 'pointer-events:' not in parent_rule

    blocked_rule_match = re.search(
        r'\.seat\.seat--blocked,\s*'
        r'\.seat\.seat--blocked\.seat--occupiable,\s*'
        r'\.seat\.seat--blocked:hover\s*'
        r'\{(?P<body>[^}]*)\}',
        css,
    )
    assert blocked_rule_match is not None
    blocked_rule = blocked_rule_match.group('body')
    assert 'background-color: #555555;' in blocked_rule
    assert 'repeating-linear-gradient(' in blocked_rule
    assert 'cursor: not-allowed;' in blocked_rule
    assert 'pointer-events: none;' in blocked_rule

    target_rule = _get_css_rule(
        css, r'\.seat-with-tooltip:target \.seat\.seat--blocked'
    )
    assert 'background-color: #555555 !important;' in target_rule


def _get_css_rule(css: str, selector_pattern: str) -> str:
    match = re.search(rf'{selector_pattern}\s*\{{(?P<body>[^}}]*)\}}', css)
    assert match is not None
    return match.group('body')


class _SeatHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.seats: dict[
            str,
            tuple[dict[str, str | None], dict[str, str | None]],
        ] = {}
        self.order: list[str] = []
        self._pending_seat: tuple[str, dict[str, str | None]] | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag != 'div':
            return

        attributes = dict(attrs)
        element_id = attributes.get('id')
        if element_id is not None and element_id.startswith('seat-'):
            seat_id = element_id.removeprefix('seat-')
            self.order.append(seat_id)
            self._pending_seat = seat_id, attributes
            return

        classes = (attributes.get('class') or '').split()
        if self._pending_seat is not None and 'seat' in classes:
            seat_id, container_attributes = self._pending_seat
            self.seats[seat_id] = container_attributes, attributes
            self._pending_seat = None
