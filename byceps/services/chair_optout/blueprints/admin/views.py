"""
byceps.services.chair_optout.blueprints.admin.views
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2026 Y0GI
:License: Revised BSD (see `LICENSE` file for details)
"""

from flask import abort
from flask_babel import gettext

from byceps.services.chair_optout import chair_optout_service
from byceps.services.party import party_service
from byceps.services.party.models import Party
from byceps.services.seating import seating_area_service, seat_service
from byceps.util.export import serialize_tuples_to_csv
from byceps.util.framework.blueprint import create_blueprint
from byceps.util.framework.templating import templated
from byceps.util.views import permission_required, textified


blueprint = create_blueprint('chair_optout_admin', __name__)


@blueprint.get('/for_party/<party_id>')
@permission_required('seating.view')
@templated('admin/chair_optout/seat_management')
def index(party_id):
    """Show the seat management landing page for a party."""
    party = _get_party_or_404(party_id)

    return {'party': party}


@blueprint.get('/for_party/<party_id>/chair_information')
@permission_required('seating.view')
@templated('admin/chair_optout/index')
def chair_information(party_id):
    """Show participant chair information for a party."""
    party = _get_party_or_404(party_id)
    report_entries = chair_optout_service.get_report_entries_for_party(party.id)
    summary = chair_optout_service.summarize_report_entries(report_entries)
    areas_with_seats = [
        (area, seat_service.get_area_seats(area.id))
        for area in seating_area_service.get_areas_for_party(party.id)
    ]
    own_chair_ticket_ids = {
        entry.ticket_id
        for entry in report_entries
        if entry.brings_own_chair is True
    }

    return {
        'party': party,
        'report_entries': report_entries,
        'summary': summary,
        'areas_with_seats': areas_with_seats,
        'own_chair_ticket_ids': own_chair_ticket_ids,
    }


@blueprint.get('/for_party/<party_id>/export.csv')
@permission_required('seating.view')
@textified
def export_as_csv(party_id):
    """Export the chair opt-out report for a party as CSV."""
    party = _get_party_or_404(party_id)

    report_entries = chair_optout_service.get_report_entries_for_party(party.id)

    header_row = (
        gettext('Name'),
        gettext('Nickname'),
        gettext('Ticket number'),
        gettext('Seat label'),
        gettext('Chair information'),
    )

    data_rows = [
        (
            entry.full_name or '',
            entry.screen_name or '',
            entry.ticket_code,
            entry.seat_label or gettext('no seat'),
            _get_status_label(entry.brings_own_chair),
        )
        for entry in report_entries
    ]

    rows = [header_row] + data_rows

    return serialize_tuples_to_csv(rows)


def _get_status_label(brings_own_chair: bool | None) -> str:
    if brings_own_chair is True:
        return gettext('Brings own chair')
    if brings_own_chair is False:
        return gettext('Needs a provided chair')
    return gettext('Not specified yet')


def _get_party_or_404(party_id) -> Party:
    party = party_service.find_party(party_id)

    if party is None:
        abort(404)

    return party
