"""
byceps.services.seating.management.models
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from dataclasses import dataclass

from byceps.services.seating.models import SeatID, SeatingArea, SeatingAreaID
from byceps.services.ticketing.models.ticket import TicketCategoryID, TicketID
from byceps.services.user.models import User


@dataclass(frozen=True, slots=True, kw_only=True)
class SeatState:
    """A seat's state relevant to administrative management."""

    id: SeatID
    area_id: SeatingAreaID
    category_id: TicketCategoryID
    label: str | None
    blocked: bool
    occupied_by_ticket_id: TicketID | None


@dataclass(frozen=True, slots=True, kw_only=True)
class BlockedSeatUpdate:
    """Describe the result of setting a seat's blocked state."""

    seat_id: SeatID
    area_id: SeatingAreaID
    label: str | None
    blocked: bool
    changed: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class ManagementSeat:
    """A seat prepared for the administrative management interface."""

    id: SeatID
    coord_x: int
    coord_y: int
    rotation: int | None
    label: str | None
    type_: str | None
    blocked: bool
    occupied: bool
    grouped: bool
    ticket_revoked: bool
    ticket_bundled: bool
    occupier: User | None

    @property
    def display_label(self) -> str:
        label = self.label.strip() if self.label else ''
        return label or str(self.id)

    @property
    def can_move_source(self) -> bool:
        return (
            self.occupied
            and not self.grouped
            and not self.ticket_revoked
            and not self.ticket_bundled
        )

    @property
    def can_swap(self) -> bool:
        return self.can_move_source and not self.blocked

    @property
    def can_move_target(self) -> bool:
        return not self.occupied and not self.blocked and not self.grouped

    @property
    def can_block(self) -> bool:
        return self.can_move_target

    @property
    def can_unblock(self) -> bool:
        return self.blocked

    @property
    def unavailable(self) -> bool:
        return self.grouped or (
            self.occupied and (self.ticket_revoked or self.ticket_bundled)
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AreaManagement:
    """A seating area and its seats for administrative management."""

    area: SeatingArea
    seats: list[ManagementSeat]
