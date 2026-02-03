"""
byceps.services.seating.blueprints.admin.views
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from uuid import UUID

from flask import abort, g, request
from flask_babel import gettext, to_utc
from sqlalchemy.exc import IntegrityError

from byceps.database import db
from byceps.services.party import party_service
from byceps.services.seating import (
    seat_group_service,
    seat_reservation_service,
    seat_service,
    seating_area_service,
    signals,
)
from byceps.services.seating.models import (
    SeatingArea,
    SeatingAreaID,
    SeatID,
    SeatGroup,
    SeatGroupID,
    SeatReservationPrecondition,
)
from byceps.services.ticketing import (
    errors as ticketing_errors,
    ticket_bundle_service,
    ticket_category_service,
    ticket_seat_management_service,
    ticket_service,
)
from byceps.services.ticketing.models.ticket import TicketBundleID
from byceps.util.framework.blueprint import create_blueprint
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.framework.templating import templated
from byceps.util.result import Err, Ok
from byceps.util.views import (
    permission_required,
    redirect_to,
    respond_no_content,
)

from . import service
from .forms import (
    AreaCreateForm,
    AreaUpdateForm,
    ReservationPreconditionCreateForm,
    SeatGroupOccupyForm,
)


blueprint = create_blueprint('seating_admin', __name__)


@blueprint.get('/<party_id>')
@permission_required('seating.view')
@templated
def index_for_party(party_id):
    """List seating areas for that party."""
    party = _get_party_or_404(party_id)

    seat_count = seat_service.count_seats_for_party(party.id)
    area_count = seating_area_service.count_areas_for_party(party.id)
    category_count = ticket_category_service.count_categories_for_party(
        party.id
    )
    group_count = seat_group_service.count_groups_for_party(party.id)

    reservation_preconditions = seat_reservation_service.get_preconditions(
        party.id
    )

    return {
        'party': party,
        'seat_count': seat_count,
        'area_count': area_count,
        'category_count': category_count,
        'group_count': group_count,
        'reservation_preconditions': reservation_preconditions,
    }


# area


@blueprint.get('/parties/<party_id>/areas')
@permission_required('seating.view')
@templated
def area_index(party_id):
    """List seating areas for that party."""
    party = _get_party_or_404(party_id)

    areas_with_utilization = seating_area_service.get_areas_with_utilization(
        party.id
    )

    seat_utilizations = [awu[1] for awu in areas_with_utilization]
    total_seat_utilization = seat_service.aggregate_seat_utilizations(
        seat_utilizations
    )

    return {
        'party': party,
        'areas_with_utilization': areas_with_utilization,
        'total_seat_utilization': total_seat_utilization,
    }


@blueprint.get('/areas/<area_id>')
@permission_required('seating.view')
@templated
def area_view(area_id):
    """Show seating area."""
    area = _get_area_or_404(area_id)

    party = party_service.get_party(area.party_id)

    seats = seat_service.get_area_seats(area.id)

    return {
        'party': party,
        'area': area,
        'seats': seats,
    }


@blueprint.get('/parties/<party_id>/areas/create')
@permission_required('seating.administrate')
@templated
def area_create_form(party_id, erroneous_form=None):
    """Show form to create a seating area."""
    party = _get_party_or_404(party_id)

    form = erroneous_form if erroneous_form else AreaCreateForm()

    return {
        'party': party,
        'form': form,
    }


@blueprint.post('/parties/<party_id>/areas')
@permission_required('seating.administrate')
def area_create(party_id):
    """Create a seating area."""
    party = _get_party_or_404(party_id)

    form = AreaCreateForm(request.form)
    if not form.validate():
        return area_create_form(party.id, form)

    slug = form.slug.data.strip()
    title = form.title.data.strip()
    image_filename = form.image_filename.data.strip()
    image_width = form.image_width.data
    image_height = form.image_height.data

    area = seating_area_service.create_area(
        party.id,
        slug,
        title,
        image_filename=image_filename,
        image_width=image_width,
        image_height=image_height,
    )

    flash_success(
        gettext('Seating area "%(title)s" has been created.', title=area.title)
    )

    return redirect_to('.area_index', party_id=party.id)


@blueprint.get('/areas/<area_id>/update')
@permission_required('seating.administrate')
@templated
def area_update_form(area_id, erroneous_form=None):
    """Show form to update a seating area."""
    area = _get_area_or_404(area_id)

    party = party_service.get_party(area.party_id)

    form = erroneous_form if erroneous_form else AreaUpdateForm(obj=area)

    return {
        'party': party,
        'area': area,
        'form': form,
    }


@blueprint.post('/areas/<area_id>')
@permission_required('seating.administrate')
def area_update(area_id):
    """Update a seating area."""
    area = _get_area_or_404(area_id)

    form = AreaUpdateForm(request.form)
    if not form.validate():
        return area_update_form(area.id, form)

    slug = form.slug.data.strip()
    title = form.title.data.strip()
    image_filename = form.image_filename.data.strip()
    image_width = form.image_width.data
    image_height = form.image_height.data

    area = seating_area_service.update_area(
        area,
        slug,
        title,
        image_filename=image_filename,
        image_width=image_width,
        image_height=image_height,
    )

    flash_success(
        gettext('Seating area "%(title)s" has been updated.', title=area.title)
    )

    return redirect_to('.area_view', area_id=area.id)


# relocate


@blueprint.get('/parties/<party_id>/relocate')
@permission_required('seating.view')
@permission_required('seating.administrate')
@templated
def relocate_index_for_party(party_id):
    """List seating areas for that party to relocate participants."""
    party = _get_party_or_404(party_id)

    areas = seating_area_service.get_areas_for_party(party.id)

    return {
        'party': party,
        'areas': areas,
        'current_tab': 'relocate',
    }


@blueprint.get('/areas/<area_id>/relocate')
@permission_required('seating.view')
@permission_required('seating.administrate')
@templated
def relocate_area(area_id):
    """Show relocate view for seating area."""
    area = _get_area_or_404(area_id)

    party = party_service.get_party(area.party_id)
    seats = seat_service.get_area_seats(area.id)

    return {
        'party': party,
        'area': area,
        'seats': seats,
        'current_tab': 'relocate',
    }


@blueprint.post('/areas/<area_id>/relocate')
@permission_required('seating.view')
@permission_required('seating.administrate')
def relocate_area_move(area_id):
    """Move a participant to a free seat in the area."""
    area = _get_area_or_404(area_id)

    def _redirect_with_error(message):
        flash_error(message)
        return redirect_to('.relocate_area', area_id=area.id)

    invalid_request_message = gettext(
        'Ungültige Angaben. Bitte neu auswählen.'
    )
    seat_status_changed_message = gettext(
        'Sitzstatus hat sich geändert. Bitte neu auswählen.'
    )
    seat_occupied_message = gettext(
        'Sitz ist inzwischen belegt. Bitte neu auswählen.'
    )

    def _get_ticket_category_title(ticket):
        category = getattr(ticket, 'category', None)
        return category.title if category else None

    def _get_seat_category_title(seat):
        category = ticket_category_service.find_category(seat.category_id)
        return category.title if category else None

    def _build_category_mismatch_message(ticket, seat):
        ticket_category_title = _get_ticket_category_title(ticket)
        seat_category_title = _get_seat_category_title(seat)

        if ticket_category_title and seat_category_title:
            return gettext(
                'Ticket %(ticket_code)s (Kategorie %(ticket_category)s) passt nicht zu Sitz "%(seat_label)s" (Kategorie %(seat_category)s).',
                ticket_code=ticket.code,
                ticket_category=ticket_category_title,
                seat_label=seat.label,
                seat_category=seat_category_title,
            )

        return gettext(
            'Ticket %(ticket_code)s und Sitz "%(seat_label)s" gehören zu unterschiedlichen Kategorien.',
            ticket_code=ticket.code,
            seat_label=seat.label,
        )

    mode = request.form.get('mode')
    if mode == 'swap':
        ticket_id_str = request.form.get('ticket_id')
        target_ticket_id_str = request.form.get('target_ticket_id')
        target_seat_id_str = request.form.get('target_seat_id')
        source_seat_id_str = request.form.get('source_seat_id')

        if (
            not ticket_id_str
            or not target_seat_id_str
            or not source_seat_id_str
        ):
            return _redirect_with_error(gettext('Benötigte Angaben fehlen.'))

        if not target_ticket_id_str:
            return _redirect_with_error(
                gettext('Zielticket fehlt. Bitte neu auswählen.')
            )

        try:
            ticket_id = UUID(ticket_id_str)
            target_ticket_id = UUID(target_ticket_id_str)
            target_seat_id = SeatID(UUID(target_seat_id_str))
            source_seat_id = SeatID(UUID(source_seat_id_str))
        except ValueError:
            return _redirect_with_error(invalid_request_message)

        try:
            source_seat = seat_service.get_seat(source_seat_id)
            target_seat = seat_service.get_seat(target_seat_id)
        except ValueError:
            return _redirect_with_error(
                gettext('Sitz wurde nicht gefunden.')
            )

        if (source_seat.area_id != area.id) or (
            target_seat.area_id != area.id
        ):
            return _redirect_with_error(
                gettext('Sitz gehört nicht zu diesem Bereich.')
            )

        source_ticket = ticket_service.find_ticket(ticket_id)
        target_ticket = ticket_service.find_ticket(target_ticket_id)
        if (source_ticket is None) or source_ticket.revoked:
            return _redirect_with_error(
                gettext('Ticket wurde nicht gefunden.')
            )
        if (target_ticket is None) or target_ticket.revoked:
            return _redirect_with_error(
                gettext('Zielticket wurde nicht gefunden.')
            )

        if (
            (source_ticket.party_id != area.party_id)
            or (target_ticket.party_id != area.party_id)
        ):
            return _redirect_with_error(
                gettext('Ticket gehört nicht zu dieser Party.')
            )

        if source_ticket.occupied_seat_id != source_seat_id:
            return _redirect_with_error(seat_status_changed_message)

        target_seat_occupier = ticket_service.find_ticket_occupying_seat(
            target_seat.id
        )
        if target_seat_occupier is None:
            return _redirect_with_error(
                gettext('Zielsitz ist inzwischen frei. Bitte neu auswählen.')
            )
        if target_seat_occupier.id != target_ticket.id:
            return _redirect_with_error(seat_status_changed_message)

        if source_ticket.category_id != target_seat.category_id:
            return _redirect_with_error(
                _build_category_mismatch_message(source_ticket, target_seat)
            )

        if target_ticket.category_id != source_seat.category_id:
            return _redirect_with_error(
                _build_category_mismatch_message(target_ticket, source_seat)
            )

        initiator = g.user

        try:
            swap_result = ticket_seat_management_service.swap_seats(
                source_ticket.id, target_ticket.id, initiator
            )
        except IntegrityError:
            return _redirect_with_error(seat_status_changed_message)

        if swap_result.is_err():
            err = swap_result.unwrap_err()
            if isinstance(
                err, ticketing_errors.SeatChangeDeniedForBundledTicketError
            ):
                return _redirect_with_error(
                    gettext(
                        'Mindestens eines der Tickets gehört zu einem Bundle und kann nicht einzeln umgesetzt werden.'
                    )
                )
            elif isinstance(
                err, ticketing_errors.SeatChangeDeniedForGroupSeatError
            ):
                return _redirect_with_error(
                    gettext(
                        'Mindestens einer der Sitze gehört zu einer Gruppe und kann nicht einzeln umgesetzt werden.'
                    )
                )
            elif isinstance(err, ticketing_errors.TicketCategoryMismatchError):
                mismatch_message = None
                if source_ticket.category_id != target_seat.category_id:
                    mismatch_message = _build_category_mismatch_message(
                        source_ticket, target_seat
                    )
                elif target_ticket.category_id != source_seat.category_id:
                    mismatch_message = _build_category_mismatch_message(
                        target_ticket, source_seat
                    )

                if mismatch_message is None:
                    mismatch_message = gettext(
                        'Tickets und Sitze gehören zu unterschiedlichen Kategorien.'
                    )

                return _redirect_with_error(mismatch_message)
            else:
                return _redirect_with_error(
                    gettext('Ein unerwarteter Fehler ist aufgetreten.')
                )

        flash_success(gettext('Plätze wurden getauscht.'))

        return redirect_to('.relocate_area', area_id=area.id)

    if mode != 'move':
        return _redirect_with_error(gettext('Aktion ist ungültig.'))

    ticket_id_str = request.form.get('ticket_id')
    target_seat_id_str = request.form.get('target_seat_id')
    source_seat_id_str = request.form.get('source_seat_id')

    if not ticket_id_str or not target_seat_id_str:
        return _redirect_with_error(gettext('Benötigte Angaben fehlen.'))

    try:
        ticket_id = UUID(ticket_id_str)
        target_seat_id = SeatID(UUID(target_seat_id_str))
        source_seat_id = (
            SeatID(UUID(source_seat_id_str))
            if source_seat_id_str
            else None
        )
    except ValueError:
        return _redirect_with_error(invalid_request_message)

    try:
        seat = seat_service.get_seat(target_seat_id)
    except ValueError:
        return _redirect_with_error(gettext('Sitz wurde nicht gefunden.'))

    if seat.area_id != area.id:
        return _redirect_with_error(
            gettext('Sitz gehört nicht zu diesem Bereich.')
        )

    ticket = ticket_service.find_ticket(ticket_id)
    if (ticket is None) or ticket.revoked:
        return _redirect_with_error(gettext('Ticket wurde nicht gefunden.'))

    if ticket.party_id != area.party_id:
        return _redirect_with_error(
            gettext('Ticket gehört nicht zu dieser Party.')
        )

    if ticket.occupied_seat_id is None:
        return _redirect_with_error(seat_status_changed_message)

    try:
        occupied_seat = seat_service.get_seat(ticket.occupied_seat_id)
    except ValueError:
        return _redirect_with_error(seat_status_changed_message)

    if occupied_seat.area_id != area.id:
        return _redirect_with_error(
            gettext('Sitz gehört nicht zu diesem Bereich.')
        )

    if source_seat_id is not None:
        if ticket.occupied_seat_id != source_seat_id:
            return _redirect_with_error(seat_status_changed_message)

    if ticket_service.find_ticket_occupying_seat(seat.id) is not None:
        return _redirect_with_error(seat_occupied_message)

    initiator = g.user

    try:
        occupy_seat_result = ticket_seat_management_service.occupy_seat(
            ticket.id, seat.id, initiator
        )
    except ValueError:
        return _redirect_with_error(gettext('Sitz wurde nicht gefunden.'))
    except IntegrityError:
        db.session.rollback()
        return _redirect_with_error(seat_occupied_message)

    if occupy_seat_result.is_err():
        err = occupy_seat_result.unwrap_err()
        if isinstance(
            err, ticketing_errors.SeatChangeDeniedForBundledTicketError
        ):
            return _redirect_with_error(
                gettext(
                    'Ticket %(ticket_code)s gehört zu einem Bundle und kann nicht einzeln umgesetzt werden.',
                    ticket_code=ticket.code,
                )
            )
        elif isinstance(
            err, ticketing_errors.SeatChangeDeniedForGroupSeatError
        ):
            return _redirect_with_error(
                gettext(
                    'Sitz "%(seat_label)s" gehört zu einer Gruppe und kann nicht einzeln umgesetzt werden.',
                    seat_label=seat.label,
                )
            )
        elif isinstance(err, ticketing_errors.TicketCategoryMismatchError):
            return _redirect_with_error(
                _build_category_mismatch_message(ticket, seat)
            )
        else:
            return _redirect_with_error(
                gettext('Ein unerwarteter Fehler ist aufgetreten.')
            )

    flash_success(gettext('Teilnehmer wurde umgesetzt.'))

    return redirect_to('.relocate_area', area_id=area.id)


# seat group


@blueprint.get('/parties/<party_id>/seat_groups')
@permission_required('seating.view')
@templated
def seat_group_index(party_id):
    """List seat groups for that party."""
    party = _get_party_or_404(party_id)

    groups_for_admin = service.get_seat_groups_for_admin(party.id)

    return {
        'party': party,
        'groups': groups_for_admin,
    }


@blueprint.get('/seat_groups/<uuid:group_id>/occupy')
@permission_required('ticketing.administrate_seat_occupancy')
@templated
def seat_group_occupy_form(group_id, erroneous_form=None):
    """Show form to occupy a seat group."""
    group = _get_seat_group_or_404(group_id)

    party = party_service.get_party(group.party_id)

    form = erroneous_form if erroneous_form else SeatGroupOccupyForm()
    form.set_ticket_bundle_id_choices(group)

    return {
        'party': party,
        'group': group,
        'form': form,
    }


@blueprint.post('/seat_groups/<uuid:group_id>/occupy')
@permission_required('ticketing.administrate_seat_occupancy')
def seat_group_occupy(group_id, erroneous_form=None):
    """Occupy a seat group."""
    group = _get_seat_group_or_404(group_id)

    party = party_service.get_party(group.party_id)

    form = SeatGroupOccupyForm(request.form)
    form.set_ticket_bundle_id_choices(group)

    if not form.validate():
        return seat_group_occupy_form(group.id, form)

    ticket_bundle_id = TicketBundleID(UUID(form.ticket_bundle_id.data))

    db_ticket_bundle = ticket_bundle_service.find_bundle(ticket_bundle_id)
    if not db_ticket_bundle:
        flash_error(gettext('Ticket bundle not found.'))
        return redirect_to('.seat_group_index', party_id=party.id)

    ticket_bundle = ticket_bundle_service.db_entity_to_ticket_bundle(
        db_ticket_bundle
    )

    initiator = g.user

    match seat_group_service.occupy_group(group, ticket_bundle, initiator):
        case Ok((_, event)):
            flash_success(
                gettext(
                    'Seat group "%(title)s" has been occupied.',
                    title=group.title,
                )
            )
            signals.seat_group_occupied.send(None, event=event)
        case Err(error):
            flash_error(
                gettext(
                    'Seat group "%(title)s" could not be occupied: %(error)s',
                    title=group.title,
                    error=error.message,
                )
            )

    return redirect_to('.seat_group_index', party_id=party.id)


@blueprint.delete('/seat_groups/<uuid:group_id>/release')
@permission_required('ticketing.administrate_seat_occupancy')
@respond_no_content
def seat_group_release(group_id):
    """Release the seat group."""
    group = _get_seat_group_or_404(group_id)

    initiator = g.user

    match seat_group_service.release_group(group.id, initiator):
        case Ok(event):
            flash_success(
                gettext(
                    'Seat group "%(title)s" has been released.',
                    title=group.title,
                )
            )
            signals.seat_group_released.send(None, event=event)
        case Err(error):
            flash_error(
                gettext(
                    'Seat group "%(title)s" could not be released: %(error)s',
                    title=group.title,
                    error=error.message,
                )
            )


# reservation precondition


@blueprint.get('/parties/<party_id>/reservation_preconditions/create')
@permission_required('seating.administrate')
@templated
def reservation_precondition_create_form(party_id, erroneous_form=None):
    """Show form to create a reservation precondition."""
    party = _get_party_or_404(party_id)

    form = (
        erroneous_form
        if erroneous_form
        else ReservationPreconditionCreateForm()
    )

    return {
        'party': party,
        'form': form,
    }


@blueprint.post('/parties/<party_id>/reservation_preconditions')
@permission_required('seating.administrate')
def reservation_precondition_create(party_id):
    """Create a reservation precondition."""
    party = _get_party_or_404(party_id)

    form = ReservationPreconditionCreateForm(request.form)
    if not form.validate():
        return reservation_precondition_create_form(party.id, form)

    at_earliest_utc = to_utc(form.at_earliest.data)
    minimum_ticket_quantity = form.minimum_ticket_quantity.data

    seat_reservation_service.create_precondition(
        party.id, at_earliest_utc, minimum_ticket_quantity
    )

    flash_success(gettext('The object has been created.'))

    return redirect_to('.index_for_party', party_id=party.id)


@blueprint.delete('/reservation_preconditions/<uuid:precondition_id>')
@permission_required('seating.administrate')
@respond_no_content
def reservation_precondition_delete(precondition_id):
    """Delete a reservation precondition."""
    precondition = _get_reservation_precondition_or_404(precondition_id)

    seat_reservation_service.delete_precondition(precondition.id)

    flash_success(gettext('The object has been deleted.'))


# helpers


def _get_party_or_404(party_id):
    party = party_service.find_party(party_id)

    if party is None:
        abort(404)

    return party


def _get_area_or_404(area_id: SeatingAreaID) -> SeatingArea:
    area = seating_area_service.find_area(area_id)

    if area is None:
        abort(404)

    return area


def _get_seat_group_or_404(group_id: SeatGroupID) -> SeatGroup:
    group = seat_group_service.find_group(group_id)

    if group is None:
        abort(404)

    return group


def _get_reservation_precondition_or_404(
    precondition_id: UUID,
) -> SeatReservationPrecondition:
    precondition = seat_reservation_service.find_precondition(precondition_id)

    if precondition is None:
        abort(404)

    return precondition
