"""
byceps.services.seating.management.blueprints.admin.views
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from uuid import UUID

from flask import abort, g, redirect, request, url_for
from flask_babel import gettext

from byceps.services.party import party_service, party_setting_service
from byceps.services.party.models import Party, PartyID
from byceps.services.seating.management import errors, service
from byceps.services.seating.models import SeatID, SeatingAreaID
from byceps.services.site import site_service
from byceps.services.ticketing import errors as ticketing_errors
from byceps.util.framework.blueprint import create_blueprint
from byceps.util.framework.flash import flash_error, flash_notice, flash_success
from byceps.util.framework.templating import templated
from byceps.util.result import Err, Ok
from byceps.util.templating import SITES_PATH
from byceps.util.views import permission_required

from .forms import RelocationForm, SeatSelectionForm


blueprint = create_blueprint('seating_management_admin', __name__)


@blueprint.get('/for_party/<party_id>')
@permission_required('seating.administrate')
@templated
def index(party_id):
    """List the party's seating areas."""
    party = _get_party_or_404(party_id)
    areas = service.get_areas_for_party(party.id)

    return {
        'party': party,
        'areas': areas,
    }


@blueprint.get('/areas/<uuid:area_id>')
@permission_required('seating.administrate')
@templated
def view_area(area_id):
    """Show the area's administrative seat management interface."""
    area_management = _get_area_management_or_404(SeatingAreaID(area_id))
    party = _get_party_or_404(area_management.area.party_id)
    forms = _build_forms(area_management.seats)

    return {
        'party': party,
        'area': area_management.area,
        'seats': area_management.seats,
        'seat_stylesheet_site_id': _find_seat_stylesheet_site_id(party.id),
        **forms,
    }


@blueprint.post('/areas/<uuid:area_id>/move')
@permission_required('seating.administrate')
def move(area_id):
    """Move a seat's occupant to a free seat."""
    area_id = SeatingAreaID(area_id)
    area_management = _get_area_management_or_404(area_id)
    form = RelocationForm(request.form)
    form.set_move_choices(area_management.seats)
    if not form.validate():
        flash_error(gettext('Please select valid source and target seats.'))
        return _redirect_to_area(area_id)

    result = service.move_occupancy(
        area_id,
        SeatID(UUID(form.source_seat_id.data)),
        SeatID(UUID(form.target_seat_id.data)),
        g.user.as_user(),
    )
    match result:
        case Ok(_):
            flash_success(gettext('The seat occupant has been moved.'))
        case Err(error):
            _handle_operation_error(error)

    return _redirect_to_area(area_id)


@blueprint.post('/areas/<uuid:area_id>/swap')
@permission_required('seating.administrate')
def swap(area_id):
    """Swap two occupied seats."""
    area_id = SeatingAreaID(area_id)
    area_management = _get_area_management_or_404(area_id)
    form = RelocationForm(request.form)
    form.set_swap_choices(area_management.seats)
    if not form.validate():
        flash_error(gettext('Please select valid source and target seats.'))
        return _redirect_to_area(area_id)

    result = service.swap_occupancies(
        area_id,
        SeatID(UUID(form.source_seat_id.data)),
        SeatID(UUID(form.target_seat_id.data)),
        g.user.as_user(),
    )
    match result:
        case Ok(_):
            flash_success(gettext('The seat occupants have been swapped.'))
        case Err(error):
            _handle_operation_error(error)

    return _redirect_to_area(area_id)


@blueprint.post('/areas/<uuid:area_id>/block')
@permission_required('seating.administrate')
def block(area_id):
    """Block a free individual seat."""
    return _set_blocked(SeatingAreaID(area_id), True)


@blueprint.post('/areas/<uuid:area_id>/unblock')
@permission_required('seating.administrate')
def unblock(area_id):
    """Unblock a seat."""
    return _set_blocked(SeatingAreaID(area_id), False)


def _set_blocked(area_id: SeatingAreaID, blocked: bool):
    area_management = _get_area_management_or_404(area_id)
    form = SeatSelectionForm(request.form)
    if blocked:
        form.set_block_choices(area_management.seats)
    else:
        form.set_unblock_choices(area_management.seats)

    if not form.validate():
        flash_error(gettext('Please select a valid seat.'))
        return _redirect_to_area(area_id)

    result = service.set_seat_blocked(
        area_id,
        SeatID(UUID(form.seat_id.data)),
        blocked,
        g.user.as_user(),
    )
    match result:
        case Ok(True):
            message = (
                gettext('The seat has been blocked.')
                if blocked
                else gettext('The seat has been unblocked.')
            )
            flash_success(message)
        case Ok(False):
            message = (
                gettext('The seat is already blocked.')
                if blocked
                else gettext('The seat is already unblocked.')
            )
            flash_notice(message)
        case Err(error):
            _handle_operation_error(error)

    return _redirect_to_area(area_id)


def _build_forms(seats):
    move_form = RelocationForm()
    move_form.set_move_choices(seats)

    swap_form = RelocationForm()
    swap_form.set_swap_choices(seats)

    block_form = SeatSelectionForm()
    block_form.set_block_choices(seats)

    unblock_form = SeatSelectionForm()
    unblock_form.set_unblock_choices(seats)

    return {
        'move_form': move_form,
        'swap_form': swap_form,
        'block_form': block_form,
        'unblock_form': unblock_form,
    }


def _handle_operation_error(error) -> None:
    if isinstance(
        error,
        errors.SeatNotFoundError | errors.SeatOutsideAreaError,
    ):
        abort(404)

    match error:
        case errors.IdenticalSeatsError():
            message = gettext('Source and target seat must differ.')
        case errors.SourceSeatNotOccupiedError():
            message = gettext('The selected source seat is not occupied.')
        case errors.TargetSeatNotFreeError():
            message = gettext('The selected move target is not free.')
        case errors.TargetSeatNotOccupiedError():
            message = gettext('The selected swap target is not occupied.')
        case errors.SeatOccupiedError():
            message = gettext(
                'This seat is occupied. Move the ticket or release the seat separately before blocking it.'
            )
        case errors.ConcurrentSeatChangeError():
            message = gettext(
                'Seat occupancy changed concurrently. Reload the page and try again.'
            )
        case ticketing_errors.SeatBlockedError():
            message = gettext(
                'Blocked seats cannot be used as relocation destinations.'
            )
        case ticketing_errors.SeatChangeDeniedForBundledTicketError():
            message = gettext('Bundle tickets cannot be moved individually.')
        case ticketing_errors.SeatChangeDeniedForGroupSeatError():
            message = gettext(
                'Seats in a seat group cannot be managed individually.'
            )
        case ticketing_errors.TicketBelongsToDifferentPartyError():
            message = gettext('The ticket belongs to a different party.')
        case ticketing_errors.TicketCategoryMismatchError():
            message = gettext(
                'The ticket categories of the seats do not match.'
            )
        case ticketing_errors.TicketIsRevokedError():
            message = gettext('Revoked tickets cannot be moved.')
        case _:
            message = gettext('The seat management operation failed.')

    flash_error(message)


def _get_party_or_404(party_id: PartyID) -> Party:
    party = party_service.find_party(party_id)
    if party is None:
        abort(404)
    return party


def _get_area_management_or_404(area_id: SeatingAreaID):
    area_management = service.find_area_management(area_id)
    if area_management is None:
        abort(404)
    return area_management


def _redirect_to_area(area_id: SeatingAreaID):
    return redirect(url_for('.view_area', area_id=area_id))


def _find_seat_stylesheet_site_id(party_id: PartyID) -> str | None:
    site_id = party_setting_service.find_setting_value(
        party_id, 'primary_party_site_id'
    )
    if site_id is not None:
        return site_id if _seat_stylesheet_exists(site_id) else None

    site_ids = [
        site.id
        for site in site_service.get_all_sites()
        if site.party_id == party_id and _seat_stylesheet_exists(site.id)
    ]
    return site_ids[0] if len(site_ids) == 1 else None


def _seat_stylesheet_exists(site_id: str) -> bool:
    if (SITES_PATH / site_id).name != site_id:
        return False

    sites_path = SITES_PATH.resolve()
    stylesheet_path = (
        SITES_PATH / site_id / 'static/style/seating.css'
    ).resolve()
    if not stylesheet_path.is_relative_to(sites_path):
        return False

    return stylesheet_path.is_file()
