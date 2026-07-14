"""
byceps.services.seating.management.errors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from dataclasses import dataclass

from byceps.services.ticketing.errors import TicketingError


@dataclass(frozen=True)
class SeatManagementError:
    """Indicate a seat management error."""

    message: str


@dataclass(frozen=True)
class SeatingAreaNotFoundError(SeatManagementError):
    """Indicate that the requested seating area does not exist."""


@dataclass(frozen=True)
class SeatNotFoundError(SeatManagementError):
    """Indicate that a requested seat does not exist."""


@dataclass(frozen=True)
class SeatOutsideAreaError(SeatManagementError):
    """Indicate that a seat does not belong to the requested area."""


@dataclass(frozen=True)
class IdenticalSeatsError(SeatManagementError):
    """Indicate that source and target are the same seat."""


@dataclass(frozen=True)
class SourceSeatNotOccupiedError(SeatManagementError):
    """Indicate that the source seat is not occupied."""


@dataclass(frozen=True)
class TargetSeatNotFreeError(SeatManagementError):
    """Indicate that a move target is occupied."""


@dataclass(frozen=True)
class TargetSeatNotOccupiedError(SeatManagementError):
    """Indicate that a swap target is not occupied."""


@dataclass(frozen=True)
class SeatOccupiedError(SeatManagementError):
    """Indicate that an occupied seat cannot be blocked."""


@dataclass(frozen=True)
class ConcurrentSeatChangeError(SeatManagementError):
    """Indicate a conflicting concurrent seat change."""


type SeatManagementOperationError = SeatManagementError | TicketingError
