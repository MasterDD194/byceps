"""
byceps.services.seating.management.blocked_seat_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from sqlalchemy import select

from byceps.database import db
from byceps.services.seating.dbmodels.seat import DbSeat
from byceps.services.seating.dbmodels.seat_group import (
    DbSeatGroupAssignment,
)
from byceps.services.seating.models import SeatID, SeatingAreaID
from byceps.services.ticketing.dbmodels.ticket import DbTicket
from byceps.services.ticketing.errors import (
    SeatChangeDeniedForGroupSeatError,
)
from byceps.util.result import Err, Ok, Result

from .errors import (
    SeatManagementOperationError,
    SeatNotFoundError,
    SeatOccupiedError,
    SeatOutsideAreaError,
)
from .models import BlockedSeatUpdate


def set_blocked_state(
    area_id: SeatingAreaID, seat_id: SeatID, blocked: bool
) -> Result[BlockedSeatUpdate, SeatManagementOperationError]:
    """Set the seat's blocked state in the current transaction.

    The caller owns the transaction and must commit or roll it back.
    """
    db_seat = db.session.scalar(
        select(DbSeat)
        .filter_by(id=seat_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if db_seat is None:
        return Err(SeatNotFoundError(f'Seat {seat_id} does not exist.'))

    if db_seat.area_id != area_id:
        return Err(
            SeatOutsideAreaError(
                f'Seat {seat_id} does not belong to seating area {area_id}.'
            )
        )

    if db_seat.blocked == blocked:
        return Ok(_build_update(db_seat, changed=False))

    if blocked:
        occupying_ticket_id = db.session.scalar(
            select(DbTicket.id).filter_by(occupied_seat_id=seat_id)
        )
        if occupying_ticket_id is not None:
            return Err(
                SeatOccupiedError(
                    f'Seat {seat_id} is occupied and cannot be blocked.'
                )
            )

        belongs_to_group = db.session.scalar(
            select(
                select(DbSeatGroupAssignment)
                .filter_by(seat_id=seat_id)
                .exists()
            )
        )
        if belongs_to_group:
            return Err(
                SeatChangeDeniedForGroupSeatError(
                    f"Seat '{db_seat.label}' belongs to a group and cannot "
                    'be blocked individually.'
                )
            )

    db_seat.blocked = blocked

    return Ok(_build_update(db_seat, changed=True))


def _build_update(db_seat: DbSeat, *, changed: bool) -> BlockedSeatUpdate:
    return BlockedSeatUpdate(
        seat_id=db_seat.id,
        area_id=db_seat.area_id,
        label=db_seat.label,
        blocked=db_seat.blocked,
        changed=changed,
    )
