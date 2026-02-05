"""
byceps.services.ticketing.ticket_seat_management_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from sqlalchemy.exc import IntegrityError

from byceps.database import db
from byceps.services.seating import seat_group_service, seat_service

# Load `Seat.assignment` backref.
from byceps.services.seating.dbmodels.seat_group import DbSeatGroup  # noqa: F401
from byceps.services.seating.models import Seat, SeatID
from byceps.services.user.models import User
from byceps.util.result import Err, Ok, Result

from . import ticket_service
from .dbmodels.ticket import DbTicket
from .errors import (
    SeatChangeDeniedForBundledTicketError,
    SeatChangeDeniedForGroupSeatError,
    TicketCategoryMismatchError,
    TicketingError,
    TicketIsRevokedError,
)
from .log import ticket_log_domain_service, ticket_log_service
from .models.ticket import TicketID


def appoint_seat_manager(
    ticket_id: TicketID, manager: User, initiator: User
) -> Result[None, TicketingError]:
    """Appoint the user as the ticket's seat manager."""
    db_ticket_result = _get_ticket(ticket_id)
    if db_ticket_result.is_err():
        return Err(db_ticket_result.unwrap_err())

    db_ticket = db_ticket_result.unwrap()

    db_ticket.seat_managed_by_id = manager.id

    log_entry = ticket_log_domain_service.build_seat_manager_appointed_entry(
        db_ticket.id, manager, initiator
    )
    db_log_entry = ticket_log_service.to_db_entry(log_entry)
    db.session.add(db_log_entry)

    db.session.commit()

    return Ok(None)


def withdraw_seat_manager(
    ticket_id: TicketID, initiator: User
) -> Result[None, TicketingError]:
    """Withdraw the ticket's custom seat manager."""
    db_ticket_result = _get_ticket(ticket_id)
    if db_ticket_result.is_err():
        return Err(db_ticket_result.unwrap_err())

    db_ticket = db_ticket_result.unwrap()

    db_ticket.seat_managed_by_id = None

    log_entry = ticket_log_domain_service.build_seat_manager_withdrawn_entry(
        db_ticket.id, initiator
    )
    db_log_entry = ticket_log_service.to_db_entry(log_entry)
    db.session.add(db_log_entry)

    db.session.commit()

    return Ok(None)


def occupy_seat(
    ticket_id: TicketID, seat_id: SeatID, initiator: User
) -> Result[None, TicketingError]:
    """Occupy the seat with this ticket."""
    db_ticket_result = _get_ticket(ticket_id)
    if db_ticket_result.is_err():
        return Err(db_ticket_result.unwrap_err())

    db_ticket = db_ticket_result.unwrap()

    ticket_belongs_to_bundle_result = (
        _deny_seat_management_if_ticket_belongs_to_bundle(db_ticket)
    )
    if ticket_belongs_to_bundle_result.is_err():
        return Err(ticket_belongs_to_bundle_result.unwrap_err())

    seat = seat_service.get_seat(seat_id)

    if seat.category_id != db_ticket.category_id:
        return Err(
            TicketCategoryMismatchError(
                'Ticket and seat belong to different categories.'
            )
        )

    seat_belongs_to_group_result = (
        _deny_seat_management_if_seat_belongs_to_group(seat)
    )
    if seat_belongs_to_group_result.is_err():
        return Err(seat_belongs_to_group_result.unwrap_err())

    previous_seat_id = db_ticket.occupied_seat_id

    db_ticket.occupied_seat_id = seat.id

    log_entry = ticket_log_domain_service.build_occupy_seat_entry(
        db_ticket.id, seat.id, previous_seat_id, initiator
    )
    db_log_entry = ticket_log_service.to_db_entry(log_entry)
    db.session.add(db_log_entry)

    db.session.commit()

    return Ok(None)


def release_seat(
    ticket_id: TicketID, initiator: User
) -> Result[None, TicketingError]:
    """Release the seat occupied by this ticket."""
    db_ticket_result = _get_ticket(ticket_id)
    if db_ticket_result.is_err():
        return Err(db_ticket_result.unwrap_err())

    db_ticket = db_ticket_result.unwrap()

    ticket_belongs_to_bundle_result = (
        _deny_seat_management_if_ticket_belongs_to_bundle(db_ticket)
    )
    if ticket_belongs_to_bundle_result.is_err():
        return Err(ticket_belongs_to_bundle_result.unwrap_err())

    if db_ticket.occupied_seat_id is None:
        return Err(TicketingError('Ticket does not occupy a seat.'))

    seat = seat_service.find_seat(db_ticket.occupied_seat_id)
    if seat is None:
        return Err(TicketingError('Ticket does not occupy a seat.'))

    seat_belongs_to_group_result = (
        _deny_seat_management_if_seat_belongs_to_group(seat)
    )
    if seat_belongs_to_group_result.is_err():
        return Err(seat_belongs_to_group_result.unwrap_err())

    db_ticket.occupied_seat_id = None

    log_entry = ticket_log_domain_service.build_release_seat_entry(
        db_ticket.id, seat.id, initiator
    )
    db_log_entry = ticket_log_service.to_db_entry(log_entry)
    db.session.add(db_log_entry)

    db.session.commit()

    return Ok(None)


def swap_seats(
    ticket_a_id: TicketID, ticket_b_id: TicketID, initiator: User
) -> Result[None, TicketingError]:
    """Swap the seats occupied by two tickets."""
    db_ticket_a_result = _get_ticket(ticket_a_id)
    if db_ticket_a_result.is_err():
        return Err(db_ticket_a_result.unwrap_err())

    db_ticket_b_result = _get_ticket(ticket_b_id)
    if db_ticket_b_result.is_err():
        return Err(db_ticket_b_result.unwrap_err())

    db_ticket_a = db_ticket_a_result.unwrap()
    db_ticket_b = db_ticket_b_result.unwrap()

    ticket_a_belongs_to_bundle_result = (
        _deny_seat_management_if_ticket_belongs_to_bundle(db_ticket_a)
    )
    if ticket_a_belongs_to_bundle_result.is_err():
        return Err(ticket_a_belongs_to_bundle_result.unwrap_err())

    ticket_b_belongs_to_bundle_result = (
        _deny_seat_management_if_ticket_belongs_to_bundle(db_ticket_b)
    )
    if ticket_b_belongs_to_bundle_result.is_err():
        return Err(ticket_b_belongs_to_bundle_result.unwrap_err())

    seat_a_id = db_ticket_a.occupied_seat_id
    seat_b_id = db_ticket_b.occupied_seat_id

    if (seat_a_id is None) or (seat_b_id is None):
        return Err(TicketingError('Ticket does not occupy a seat.'))

    seat_a = seat_service.get_seat(seat_a_id)
    seat_b = seat_service.get_seat(seat_b_id)

    if (
        (seat_a.category_id != db_ticket_b.category_id)
        or (seat_b.category_id != db_ticket_a.category_id)
    ):
        return Err(
            TicketCategoryMismatchError(
                'Ticket and seat belong to different categories.'
            )
        )

    seat_a_belongs_to_group_result = (
        _deny_seat_management_if_seat_belongs_to_group(seat_a)
    )
    if seat_a_belongs_to_group_result.is_err():
        return Err(seat_a_belongs_to_group_result.unwrap_err())

    seat_b_belongs_to_group_result = (
        _deny_seat_management_if_seat_belongs_to_group(seat_b)
    )
    if seat_b_belongs_to_group_result.is_err():
        return Err(seat_b_belongs_to_group_result.unwrap_err())

    try:
        db_ticket_a.occupied_seat_id = None
        db.session.flush()

        db_ticket_b.occupied_seat_id = seat_a.id
        db.session.flush()

        db_ticket_a.occupied_seat_id = seat_b.id

        log_entry_a = ticket_log_domain_service.build_occupy_seat_entry(
            db_ticket_a.id, seat_b.id, seat_a.id, initiator
        )
        log_entry_b = ticket_log_domain_service.build_occupy_seat_entry(
            db_ticket_b.id, seat_a.id, seat_b.id, initiator
        )
        db.session.add(ticket_log_service.to_db_entry(log_entry_a))
        db.session.add(ticket_log_service.to_db_entry(log_entry_b))

        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise

    return Ok(None)


def _get_ticket(ticket_id: TicketID) -> Result[DbTicket, TicketIsRevokedError]:
    """Return the ticket with that ID.

    Raise an exception if the ID is unknown.

    Return an error if the ticket has been revoked.
    """
    db_ticket = ticket_service.get_ticket(ticket_id)

    if db_ticket.revoked:
        return Err(
            TicketIsRevokedError(f'Ticket {ticket_id} has been revoked.')
        )

    return Ok(db_ticket)


def _deny_seat_management_if_ticket_belongs_to_bundle(
    db_ticket: DbTicket,
) -> Result[None, SeatChangeDeniedForBundledTicketError]:
    """Return an error if this ticket belongs to a bundle.

    A ticket bundle is meant to occupy a matching seat group with the
    appropriate mechanism, not to separately occupy single seats.
    """
    if db_ticket.belongs_to_bundle:
        return Err(
            SeatChangeDeniedForBundledTicketError(
                f"Ticket '{db_ticket.code}' belongs to a bundle and, thus, "
                'must not be used to occupy or release a single seat.'
            )
        )

    return Ok(None)


def _deny_seat_management_if_seat_belongs_to_group(
    seat: Seat,
) -> Result[None, SeatChangeDeniedForGroupSeatError]:
    if seat_group_service.is_seat_part_of_a_group(seat.id):
        return Err(
            SeatChangeDeniedForGroupSeatError(
                f"Seat '{seat.label}' belongs to a group and, thus, "
                'cannot be occupied by a single ticket, or removed separately.'
            )
        )

    return Ok(None)
