"""
byceps.services.seating.management.service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
import structlog

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.seating.dbmodels.area import DbSeatingArea
from byceps.services.seating.dbmodels.seat import DbSeat
from byceps.services.seating.dbmodels.seat_group import (
    DbSeatGroupAssignment,
)
from byceps.services.seating import seating_area_service
from byceps.services.seating.models import (
    SeatID,
    SeatingArea,
    SeatingAreaID,
)
from byceps.services.ticketing.dbmodels.ticket import DbTicket
from byceps.services.ticketing.errors import (
    SeatBlockedError,
    SeatChangeDeniedForBundledTicketError,
    SeatChangeDeniedForGroupSeatError,
    TicketBelongsToDifferentPartyError,
    TicketCategoryMismatchError,
    TicketIsRevokedError,
)
from byceps.services.ticketing.log import (
    ticket_log_domain_service,
    ticket_log_service,
)
from byceps.services.ticketing.models.ticket import TicketID
from byceps.services.user import user_service
from byceps.services.user.models import User, UserID
from byceps.util.result import Err, Ok, Result

from . import blocked_seat_service
from .errors import (
    ConcurrentSeatChangeError,
    IdenticalSeatsError,
    SeatManagementOperationError,
    SeatingAreaNotFoundError,
    SeatNotFoundError,
    SeatOutsideAreaError,
    SourceSeatNotOccupiedError,
    TargetSeatNotFreeError,
    TargetSeatNotOccupiedError,
)
from .models import AreaManagement, ManagementSeat, SeatState


log = structlog.get_logger()


_OCCUPIED_SEAT_CONSTRAINT_NAMES = frozenset(
    {
        'ix_tickets_occupied_seat_id',
        'tickets_occupied_seat_id_key',
    }
)


@dataclass(kw_only=True)
class _LockedSeatContext:
    party_id: PartyID
    source_seat: DbSeat
    target_seat: DbSeat
    source_ticket: DbTicket | None
    target_ticket: DbTicket | None


def get_areas_for_party(party_id: PartyID) -> list[SeatingArea]:
    """Return the party's seating areas ordered by title."""
    areas = seating_area_service.get_areas_for_party(party_id)
    return sorted(areas, key=lambda area: area.title.casefold())


def find_area_management(
    area_id: SeatingAreaID,
) -> AreaManagement | None:
    """Return the area and its current management state, if it exists."""
    area = seating_area_service.find_area(area_id)
    if area is None:
        return None

    db_seats = (
        db.session.scalars(
            select(DbSeat)
            .filter_by(area_id=area_id)
            .options(db.joinedload(DbSeat.occupied_by_ticket))
            .order_by(DbSeat.coord_y, DbSeat.coord_x, DbSeat.id)
        )
        .unique()
        .all()
    )
    seat_ids = {db_seat.id for db_seat in db_seats}
    grouped_seat_ids = set(
        db.session.scalars(
            select(DbSeatGroupAssignment.seat_id).filter(
                DbSeatGroupAssignment.seat_id.in_(seat_ids)
            )
        ).all()
    )
    occupier_ids = {
        db_seat.occupied_by_ticket.used_by_id
        for db_seat in db_seats
        if db_seat.occupied_by_ticket is not None
        and db_seat.occupied_by_ticket.used_by_id is not None
    }
    occupiers_by_id = user_service.get_users_indexed_by_id(
        occupier_ids, include_avatars=True
    )

    seats = [
        _build_management_seat(db_seat, grouped_seat_ids, occupiers_by_id)
        for db_seat in db_seats
    ]
    return AreaManagement(area=area, seats=seats)


def _build_management_seat(
    db_seat: DbSeat,
    grouped_seat_ids: set[SeatID],
    occupiers_by_id: dict[UserID, User],
) -> ManagementSeat:
    db_ticket = db_seat.occupied_by_ticket
    occupied = db_ticket is not None
    occupier = (
        occupiers_by_id.get(db_ticket.used_by_id)
        if db_ticket is not None and db_ticket.used_by_id is not None
        else None
    )

    return ManagementSeat(
        id=db_seat.id,
        coord_x=db_seat.coord_x,
        coord_y=db_seat.coord_y,
        rotation=db_seat.rotation,
        label=db_seat.label,
        type_=db_seat.type_,
        blocked=db_seat.blocked,
        occupied=occupied,
        grouped=db_seat.id in grouped_seat_ids,
        ticket_revoked=db_ticket.revoked if db_ticket is not None else False,
        ticket_bundled=(
            db_ticket.belongs_to_bundle if db_ticket is not None else False
        ),
        occupier=occupier,
    )


def move_occupancy(
    area_id: SeatingAreaID,
    source_seat_id: SeatID,
    target_seat_id: SeatID,
    initiator: User,
) -> Result[None, SeatManagementOperationError]:
    """Move the source seat's occupant to the free target seat."""
    return _relocate(
        area_id,
        source_seat_id,
        target_seat_id,
        initiator,
        swap=False,
    )


def swap_occupancies(
    area_id: SeatingAreaID,
    source_seat_id: SeatID,
    target_seat_id: SeatID,
    initiator: User,
) -> Result[None, SeatManagementOperationError]:
    """Swap the occupants of the source and target seats."""
    return _relocate(
        area_id,
        source_seat_id,
        target_seat_id,
        initiator,
        swap=True,
    )


def set_seat_blocked(
    area_id: SeatingAreaID,
    seat_id: SeatID,
    blocked: bool,
    initiator: User,
) -> Result[bool, SeatManagementOperationError]:
    """Set the seat's blocked state and return whether it changed."""
    try:
        update_result = blocked_seat_service.set_blocked_state(
            area_id, seat_id, blocked
        )
        if update_result.is_err():
            db.session.rollback()
            return Err(update_result.unwrap_err())

        update = update_result.unwrap()
        db.session.commit()
    except DBAPIError as exc:
        return _handle_database_error(exc)
    except Exception:
        db.session.rollback()
        raise

    if update.changed:
        event = 'Seat blocked' if update.blocked else 'Seat unblocked'
        log.info(
            event,
            seating_area_id=str(update.area_id),
            seat_id=str(update.seat_id),
            seat_label=update.label,
            initiator_id=str(initiator.id),
            initiator_screen_name=initiator.screen_name,
        )

    return Ok(update.changed)


def _relocate(
    area_id: SeatingAreaID,
    source_seat_id: SeatID,
    target_seat_id: SeatID,
    initiator: User,
    *,
    swap: bool,
) -> Result[None, SeatManagementOperationError]:
    try:
        context_result = _lock_and_validate(
            area_id, source_seat_id, target_seat_id, swap=swap
        )
        if context_result.is_err():
            db.session.rollback()
            return Err(context_result.unwrap_err())

        context = context_result.unwrap()
        if swap:
            _swap(context, initiator)
        else:
            _move(context, initiator)

        db.session.commit()
    except DBAPIError as exc:
        return _handle_database_error(exc)
    except Exception:
        db.session.rollback()
        raise

    return Ok(None)


def _lock_and_validate(
    area_id: SeatingAreaID,
    source_seat_id: SeatID,
    target_seat_id: SeatID,
    *,
    swap: bool,
) -> Result[_LockedSeatContext, SeatManagementOperationError]:
    if source_seat_id == target_seat_id:
        return Err(IdenticalSeatsError('Source and target seat are identical.'))

    seat_ids = {source_seat_id, target_seat_id}
    baseline_states = _get_seat_states(seat_ids)
    missing_seat_ids = seat_ids - baseline_states.keys()
    if missing_seat_ids:
        missing_seat_id = min(missing_seat_ids)
        return Err(SeatNotFoundError(f'Seat {missing_seat_id} does not exist.'))

    expected_ticket_ids = {
        state.occupied_by_ticket_id
        for state in baseline_states.values()
        if state.occupied_by_ticket_id is not None
    }
    db_tickets = _lock_tickets_for_update(expected_ticket_ids)
    if {ticket.id for ticket in db_tickets} != expected_ticket_ids:
        return Err(_concurrent_change_error())

    db_seats = _lock_seats_for_update(seat_ids)
    if {seat.id for seat in db_seats} != seat_ids:
        return Err(_concurrent_change_error())

    current_states = _get_seat_states(seat_ids)
    if not _occupancies_match(baseline_states, current_states):
        return Err(_concurrent_change_error())

    seats_by_id = {seat.id: seat for seat in db_seats}
    tickets_by_id = {ticket.id: ticket for ticket in db_tickets}
    source_state = current_states[source_seat_id]
    target_state = current_states[target_seat_id]
    source_ticket = _find_ticket_for_state(source_state, tickets_by_id)
    target_ticket = _find_ticket_for_state(target_state, tickets_by_id)

    party_id = db.session.scalar(
        select(DbSeatingArea.party_id).filter_by(id=area_id)
    )
    if party_id is None:
        return Err(
            SeatingAreaNotFoundError(f'Seating area {area_id} does not exist.')
        )

    context = _LockedSeatContext(
        party_id=party_id,
        source_seat=seats_by_id[source_seat_id],
        target_seat=seats_by_id[target_seat_id],
        source_ticket=source_ticket,
        target_ticket=target_ticket,
    )

    validation_error = _validate_context(context, area_id, swap=swap)
    if validation_error is not None:
        return Err(validation_error)

    return Ok(context)


def _get_seat_states(seat_ids: set[SeatID]) -> dict[SeatID, SeatState]:
    rows = db.session.execute(
        select(
            DbSeat.id.label('seat_id'),
            DbSeat.area_id,
            DbSeat.category_id,
            DbSeat.label,
            DbSeat.blocked,
            DbTicket.id.label('ticket_id'),
        )
        .outerjoin(DbTicket, DbTicket.occupied_seat_id == DbSeat.id)
        .filter(DbSeat.id.in_(seat_ids))
    ).all()

    return {
        row.seat_id: SeatState(
            id=row.seat_id,
            area_id=row.area_id,
            category_id=row.category_id,
            label=row.label,
            blocked=row.blocked,
            occupied_by_ticket_id=row.ticket_id,
        )
        for row in rows
    }


def _lock_tickets_for_update(ticket_ids: set[TicketID]) -> list[DbTicket]:
    if not ticket_ids:
        return []

    return list(
        db.session.scalars(
            select(DbTicket)
            .filter(DbTicket.id.in_(ticket_ids))
            .order_by(DbTicket.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )


def _lock_seats_for_update(seat_ids: set[SeatID]) -> list[DbSeat]:
    return list(
        db.session.scalars(
            select(DbSeat)
            .filter(DbSeat.id.in_(seat_ids))
            .order_by(DbSeat.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )


def _occupancies_match(
    baseline_states: dict[SeatID, SeatState],
    current_states: dict[SeatID, SeatState],
) -> bool:
    if baseline_states.keys() != current_states.keys():
        return False

    return all(
        baseline_states[seat_id].occupied_by_ticket_id
        == current_states[seat_id].occupied_by_ticket_id
        for seat_id in baseline_states
    )


def _find_ticket_for_state(
    state: SeatState, tickets_by_id: dict[TicketID, DbTicket]
) -> DbTicket | None:
    ticket_id = state.occupied_by_ticket_id
    return tickets_by_id.get(ticket_id) if ticket_id is not None else None


def _validate_context(
    context: _LockedSeatContext,
    area_id: SeatingAreaID,
    *,
    swap: bool,
) -> SeatManagementOperationError | None:
    source_seat = context.source_seat
    target_seat = context.target_seat
    source_ticket = context.source_ticket
    target_ticket = context.target_ticket

    for seat in source_seat, target_seat:
        if seat.area_id != area_id:
            return SeatOutsideAreaError(
                f'Seat {seat.id} does not belong to seating area {area_id}.'
            )

    if source_ticket is None:
        return SourceSeatNotOccupiedError(
            f'Source seat {source_seat.id} is not occupied.'
        )

    if swap:
        if target_ticket is None:
            return TargetSeatNotOccupiedError(
                f'Target seat {target_seat.id} is not occupied.'
            )
    elif target_ticket is not None:
        return TargetSeatNotFreeError(
            f'Target seat {target_seat.id} is occupied.'
        )

    tickets = [source_ticket]
    if target_ticket is not None:
        tickets.append(target_ticket)

    for ticket in tickets:
        if ticket.party_id != context.party_id:
            return TicketBelongsToDifferentPartyError(
                f'Ticket {ticket.id} belongs to a different party.'
            )
        if ticket.revoked:
            return TicketIsRevokedError(f'Ticket {ticket.id} has been revoked.')
        if ticket.belongs_to_bundle:
            return SeatChangeDeniedForBundledTicketError(
                f"Ticket '{ticket.code}' belongs to a bundle and cannot be "
                'moved individually.'
            )

    grouped_seat_ids = set(
        db.session.scalars(
            select(DbSeatGroupAssignment.seat_id).filter(
                DbSeatGroupAssignment.seat_id.in_(
                    {source_seat.id, target_seat.id}
                )
            )
        ).all()
    )
    if grouped_seat_ids:
        grouped_seat_id = min(grouped_seat_ids)
        grouped_seat = (
            source_seat if source_seat.id == grouped_seat_id else target_seat
        )
        return SeatChangeDeniedForGroupSeatError(
            f"Seat '{grouped_seat.label}' belongs to a group and cannot be "
            'moved individually.'
        )

    if target_seat.blocked:
        return SeatBlockedError(f'Seat {target_seat.label} is blocked.')
    if swap and source_seat.blocked:
        return SeatBlockedError(f'Seat {source_seat.label} is blocked.')

    if source_ticket.category_id != source_seat.category_id:
        return _category_mismatch_error()
    if source_ticket.category_id != target_seat.category_id:
        return _category_mismatch_error()

    if target_ticket is not None:
        if target_ticket.category_id != target_seat.category_id:
            return _category_mismatch_error()
        if target_ticket.category_id != source_seat.category_id:
            return _category_mismatch_error()

    return None


def _move(context: _LockedSeatContext, initiator: User) -> None:
    source_ticket = context.source_ticket
    if source_ticket is None:
        raise RuntimeError('Move source ticket unexpectedly missing.')

    previous_seat_id = context.source_seat.id
    source_ticket.occupied_seat_id = context.target_seat.id
    _add_occupy_log_entry(
        source_ticket, context.target_seat.id, previous_seat_id, initiator
    )
    db.session.flush()


def _swap(context: _LockedSeatContext, initiator: User) -> None:
    source_ticket = context.source_ticket
    target_ticket = context.target_ticket
    if source_ticket is None or target_ticket is None:
        raise RuntimeError('Swap ticket unexpectedly missing.')

    source_ticket.occupied_seat_id = None
    target_ticket.occupied_seat_id = None
    db.session.flush()

    source_ticket.occupied_seat_id = context.target_seat.id
    target_ticket.occupied_seat_id = context.source_seat.id

    _add_occupy_log_entry(
        source_ticket,
        context.target_seat.id,
        context.source_seat.id,
        initiator,
    )
    _add_occupy_log_entry(
        target_ticket,
        context.source_seat.id,
        context.target_seat.id,
        initiator,
    )


def _add_occupy_log_entry(
    db_ticket: DbTicket,
    seat_id: SeatID,
    previous_seat_id: SeatID,
    initiator: User,
) -> None:
    log_entry = ticket_log_domain_service.build_occupy_seat_entry(
        db_ticket.id, seat_id, previous_seat_id, initiator
    )
    db_log_entry = ticket_log_service.to_db_entry(log_entry)
    db.session.add(db_log_entry)


def _category_mismatch_error() -> TicketCategoryMismatchError:
    return TicketCategoryMismatchError(
        'Ticket and seat belong to different categories.'
    )


def _concurrent_change_error() -> ConcurrentSeatChangeError:
    return ConcurrentSeatChangeError(
        'Seat occupancy changed concurrently. Please reload and try again.'
    )


def _handle_database_error(
    exc: DBAPIError,
) -> Err[SeatManagementOperationError]:
    db.session.rollback()

    if _is_recognized_concurrency_error(exc):
        return Err(_concurrent_change_error())

    raise exc


def _is_recognized_concurrency_error(exc: DBAPIError) -> bool:
    sqlstate = getattr(exc.orig, 'sqlstate', None)
    if sqlstate in {'40P01', '40001'}:
        return True

    constraint_name = _get_constraint_name(exc)
    if isinstance(exc, IntegrityError) and sqlstate == '23505':
        return constraint_name in _OCCUPIED_SEAT_CONSTRAINT_NAMES

    return False


def _get_constraint_name(exc: DBAPIError) -> str | None:
    diag = getattr(exc.orig, 'diag', None)
    return getattr(diag, 'constraint_name', None) or getattr(
        exc.orig, 'constraint_name', None
    )
