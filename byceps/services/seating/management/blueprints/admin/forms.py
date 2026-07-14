"""
byceps.services.seating.management.blueprints.admin.forms
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from collections.abc import Iterable
import re

from flask_babel import gettext, lazy_gettext
from wtforms import SelectField
from wtforms.validators import InputRequired, UUID as UUIDValidator

from byceps.services.seating.management.models import ManagementSeat
from byceps.util.l10n import LocalizedForm


class RelocationForm(LocalizedForm):
    source_seat_id = SelectField(
        lazy_gettext('Source seat'),
        validators=[InputRequired(), UUIDValidator()],
        validate_choice=False,
    )
    target_seat_id = SelectField(
        lazy_gettext('Target seat'),
        validators=[InputRequired(), UUIDValidator()],
        validate_choice=False,
    )

    def set_move_choices(self, seats: list[ManagementSeat]) -> None:
        self.source_seat_id.choices = _build_choices(
            seat for seat in seats if seat.can_move_source
        )
        self.target_seat_id.choices = _build_choices(
            seat for seat in seats if seat.can_move_target
        )

    def set_swap_choices(self, seats: list[ManagementSeat]) -> None:
        choices = _build_choices(seat for seat in seats if seat.can_swap)
        self.source_seat_id.choices = choices
        self.target_seat_id.choices = choices.copy()


class SeatSelectionForm(LocalizedForm):
    seat_id = SelectField(
        lazy_gettext('Seat'),
        validators=[InputRequired(), UUIDValidator()],
        validate_choice=False,
    )

    def set_block_choices(self, seats: list[ManagementSeat]) -> None:
        self.seat_id.choices = _build_choices(
            seat for seat in seats if seat.can_block
        )

    def set_unblock_choices(self, seats: list[ManagementSeat]) -> None:
        self.seat_id.choices = _build_choices(
            seat for seat in seats if seat.can_unblock
        )


def _build_choices(
    seats: Iterable[ManagementSeat],
) -> list[tuple[str, str]]:
    choices = [('', f'<{gettext("choose")}>')]
    choices.extend(
        (str(seat.id), _build_choice_label(seat))
        for seat in sorted(seats, key=_natural_sort_key)
    )
    return choices


def _natural_sort_key(
    seat: ManagementSeat,
) -> tuple[int, tuple[tuple[int, int, str], ...], str]:
    label = seat.label.strip() if seat.label else ''
    if not label:
        return (1, (), str(seat.id))

    label_parts = tuple(
        _natural_sort_part(part) for part in re.split(r'(\d+)', label) if part
    )
    return (0, label_parts, str(seat.id))


def _natural_sort_part(part: str) -> tuple[int, int, str]:
    if not part.isdecimal():
        return (0, 0, part.casefold())

    normalized_number = part.lstrip('0') or '0'
    return (1, len(normalized_number), normalized_number)


def _build_choice_label(seat: ManagementSeat) -> str:
    states = []
    if seat.occupied:
        if seat.occupier and seat.occupier.screen_name:
            states.append(
                gettext(
                    'occupied by %(screen_name)s',
                    screen_name=seat.occupier.screen_name,
                )
            )
        else:
            states.append(gettext('occupied'))
    if seat.blocked:
        states.append(gettext('blocked'))
    if seat.grouped:
        states.append(gettext('group seat'))

    if not states:
        return seat.display_label

    return f'{seat.display_label} ({", ".join(states)})'
