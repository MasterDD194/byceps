"""
:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

import pytest

from byceps.database import db
from byceps.services.seating.dbmodels.seat import DbSeat
from byceps.services.seating.management import service
from byceps.services.seating.management.errors import (
    ConcurrentSeatChangeError,
    IdenticalSeatsError,
    SeatNotFoundError,
    SeatOutsideAreaError,
    SeatingAreaNotFoundError,
    SourceSeatNotOccupiedError,
    TargetSeatNotFreeError,
    TargetSeatNotOccupiedError,
)
from byceps.services.seating.models import SeatID, SeatingAreaID
from byceps.services.ticketing import (
    ticket_bundle_service,
    ticket_service,
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
from byceps.services.ticketing.log import ticket_log_service

from tests.helpers import generate_uuid


def test_move_occupancy_and_log(
    admin_app,
    category,
    make_area,
    make_seat,
    make_ticket,
    management_initiator,
):
    area = make_area()
    source_seat = make_seat(area, category)
    target_seat = make_seat(area, category)
    ticket = make_ticket(category, seat=source_seat)
    ticket_id = ticket.id
    previous_log_count = len(_get_log_entries(ticket_id))

    result = service.move_occupancy(
        area.id,
        source_seat.id,
        target_seat.id,
        management_initiator,
    )

    assert result.is_ok()
    assert _get_occupied_seat_id(ticket_id) == target_seat.id
    log_entries = _get_log_entries(ticket_id)
    assert len(log_entries) == previous_log_count + 1
    assert log_entries[-1].event_type == 'seat-occupied'
    assert log_entries[-1].data == {
        'seat_id': str(target_seat.id),
        'previous_seat_id': str(source_seat.id),
        'initiator_id': str(management_initiator.id),
    }


def test_swap_occupancies_and_logs(
    admin_app,
    category,
    make_area,
    make_seat,
    make_ticket,
    management_initiator,
):
    area = make_area()
    source_seat = make_seat(area, category)
    target_seat = make_seat(area, category)
    source_ticket = make_ticket(category, seat=source_seat)
    target_ticket = make_ticket(category, seat=target_seat)
    source_ticket_id = source_ticket.id
    target_ticket_id = target_ticket.id
    source_log_count = len(_get_log_entries(source_ticket_id))
    target_log_count = len(_get_log_entries(target_ticket_id))

    result = service.swap_occupancies(
        area.id,
        source_seat.id,
        target_seat.id,
        management_initiator,
    )

    assert result.is_ok()
    assert _get_occupied_seat_id(source_ticket_id) == target_seat.id
    assert _get_occupied_seat_id(target_ticket_id) == source_seat.id

    source_logs = _get_log_entries(source_ticket_id)
    target_logs = _get_log_entries(target_ticket_id)
    assert len(source_logs) == source_log_count + 1
    assert len(target_logs) == target_log_count + 1
    assert source_logs[-1].event_type == 'seat-occupied'
    assert source_logs[-1].data == {
        'seat_id': str(target_seat.id),
        'previous_seat_id': str(source_seat.id),
        'initiator_id': str(management_initiator.id),
    }
    assert target_logs[-1].event_type == 'seat-occupied'
    assert target_logs[-1].data == {
        'seat_id': str(source_seat.id),
        'previous_seat_id': str(target_seat.id),
        'initiator_id': str(management_initiator.id),
    }


def test_reject_identical_source_and_target(
    admin_app,
    category,
    make_area,
    make_seat,
    make_ticket,
    management_initiator,
):
    area = make_area()
    seat = make_seat(area, category)
    ticket = make_ticket(category, seat=seat)

    result = service.move_occupancy(
        area.id, seat.id, seat.id, management_initiator
    )

    assert isinstance(result.unwrap_err(), IdenticalSeatsError)
    assert _get_occupied_seat_id(ticket.id) == seat.id


def test_reject_unoccupied_source(
    admin_app,
    category,
    make_area,
    make_seat,
    management_initiator,
):
    area = make_area()
    source_seat = make_seat(area, category)
    target_seat = make_seat(area, category)

    result = service.move_occupancy(
        area.id,
        source_seat.id,
        target_seat.id,
        management_initiator,
    )

    assert isinstance(result.unwrap_err(), SourceSeatNotOccupiedError)


def test_reject_occupied_move_target(
    admin_app,
    category,
    make_area,
    make_seat,
    make_ticket,
    management_initiator,
):
    area = make_area()
    source_seat = make_seat(area, category)
    target_seat = make_seat(area, category)
    source_ticket = make_ticket(category, seat=source_seat)
    target_ticket = make_ticket(category, seat=target_seat)

    result = service.move_occupancy(
        area.id,
        source_seat.id,
        target_seat.id,
        management_initiator,
    )

    assert isinstance(result.unwrap_err(), TargetSeatNotFreeError)
    assert _get_occupied_seat_id(source_ticket.id) == source_seat.id
    assert _get_occupied_seat_id(target_ticket.id) == target_seat.id


def test_reject_free_swap_target(
    admin_app,
    category,
    make_area,
    make_seat,
    make_ticket,
    management_initiator,
):
    area = make_area()
    source_seat = make_seat(area, category)
    target_seat = make_seat(area, category)
    source_ticket = make_ticket(category, seat=source_seat)

    result = service.swap_occupancies(
        area.id,
        source_seat.id,
        target_seat.id,
        management_initiator,
    )

    assert isinstance(result.unwrap_err(), TargetSeatNotOccupiedError)
    assert _get_occupied_seat_id(source_ticket.id) == source_seat.id


def test_reject_seats_from_different_areas(
    admin_app,
    category,
    make_area,
    make_seat,
    make_ticket,
    management_initiator,
):
    area = make_area()
    other_area = make_area()
    source_seat = make_seat(area, category)
    target_seat = make_seat(other_area, category)
    source_ticket = make_ticket(category, seat=source_seat)

    result = service.move_occupancy(
        area.id,
        source_seat.id,
        target_seat.id,
        management_initiator,
    )

    assert isinstance(result.unwrap_err(), SeatOutsideAreaError)
    assert _get_occupied_seat_id(source_ticket.id) == source_seat.id


def test_reject_seats_from_different_parties(
    admin_app,
    party,
    another_party,
    category,
    make_area,
    make_seat,
    make_ticket,
    make_ticket_category,
    management_initiator,
):
    area = make_area(for_party=party)
    other_area = make_area(for_party=another_party)
    other_category = make_ticket_category(
        another_party.id, str(generate_uuid())
    )
    source_seat = make_seat(area, category)
    target_seat = make_seat(other_area, other_category)
    source_ticket = make_ticket(category, seat=source_seat)

    result = service.move_occupancy(
        area.id,
        source_seat.id,
        target_seat.id,
        management_initiator,
    )

    assert isinstance(result.unwrap_err(), SeatOutsideAreaError)
    assert _get_occupied_seat_id(source_ticket.id) == source_seat.id


def test_reject_ticket_party_mismatch(
    admin_app,
    another_party,
    category,
    make_area,
    make_seat,
    make_ticket,
    management_initiator,
):
    area = make_area()
    source_seat = make_seat(area, category)
    target_seat = make_seat(area, category)
    ticket = make_ticket(category, seat=source_seat)
    ticket.party_id = another_party.id
    db.session.commit()

    result = service.move_occupancy(
        area.id,
        source_seat.id,
        target_seat.id,
        management_initiator,
    )

    assert isinstance(result.unwrap_err(), TicketBelongsToDifferentPartyError)
    assert _get_occupied_seat_id(ticket.id) == source_seat.id


def test_reject_incompatible_category(
    admin_app,
    category,
    another_category,
    make_area,
    make_seat,
    make_ticket,
    management_initiator,
):
    area = make_area()
    source_seat = make_seat(area, category)
    target_seat = make_seat(area, another_category)
    ticket = make_ticket(category, seat=source_seat)

    result = service.move_occupancy(
        area.id,
        source_seat.id,
        target_seat.id,
        management_initiator,
    )

    assert isinstance(result.unwrap_err(), TicketCategoryMismatchError)
    assert _get_occupied_seat_id(ticket.id) == source_seat.id


def test_reject_swap_with_incompatible_categories(
    admin_app,
    category,
    another_category,
    make_area,
    make_seat,
    make_ticket,
    management_initiator,
):
    area = make_area()
    source_seat = make_seat(area, category)
    target_seat = make_seat(area, another_category)
    source_ticket = make_ticket(category, seat=source_seat)
    target_ticket = make_ticket(another_category, seat=target_seat)

    result = service.swap_occupancies(
        area.id,
        source_seat.id,
        target_seat.id,
        management_initiator,
    )

    assert isinstance(result.unwrap_err(), TicketCategoryMismatchError)
    assert _get_occupied_seat_id(source_ticket.id) == source_seat.id
    assert _get_occupied_seat_id(target_ticket.id) == target_seat.id


def test_reject_blocked_move_target(
    admin_app,
    category,
    make_area,
    make_seat,
    make_ticket,
    management_initiator,
):
    area = make_area()
    source_seat = make_seat(area, category)
    target_seat = make_seat(area, category)
    ticket = make_ticket(category, seat=source_seat)
    service.set_seat_blocked(
        area.id, target_seat.id, True, management_initiator
    ).unwrap()

    result = service.move_occupancy(
        area.id,
        source_seat.id,
        target_seat.id,
        management_initiator,
    )

    assert isinstance(result.unwrap_err(), SeatBlockedError)
    assert _get_occupied_seat_id(ticket.id) == source_seat.id


def test_move_from_blocked_occupied_source_repairs_state(
    admin_app,
    category,
    make_area,
    make_seat,
    make_ticket,
    management_initiator,
):
    area = make_area()
    source_seat = make_seat(area, category)
    target_seat = make_seat(area, category)
    ticket = make_ticket(category, seat=source_seat)
    db.session.get(DbSeat, source_seat.id).blocked = True
    db.session.commit()

    result = service.move_occupancy(
        area.id,
        source_seat.id,
        target_seat.id,
        management_initiator,
    )

    assert result.is_ok()
    assert _get_occupied_seat_id(ticket.id) == target_seat.id
    assert _get_blocked(source_seat.id) is True


def test_reject_move_with_revoked_ticket(
    admin_app,
    category,
    make_area,
    make_seat,
    make_ticket,
    management_initiator,
):
    area = make_area()
    source_seat = make_seat(area, category)
    target_seat = make_seat(area, category)
    ticket = make_ticket(category, seat=source_seat)
    ticket.revoked = True
    db.session.commit()

    result = service.move_occupancy(
        area.id,
        source_seat.id,
        target_seat.id,
        management_initiator,
    )

    assert isinstance(result.unwrap_err(), TicketIsRevokedError)
    assert _get_occupied_seat_id(ticket.id) == source_seat.id


def test_reject_move_with_bundled_ticket(
    admin_app,
    category,
    make_area,
    make_seat,
    management_initiator,
    ticket_owner,
):
    area = make_area()
    source_seat = make_seat(area, category)
    target_seat = make_seat(area, category)
    bundled_ticket = _make_bundled_ticket(category, ticket_owner)
    bundled_ticket.occupied_seat_id = source_seat.id
    db.session.commit()

    result = service.move_occupancy(
        area.id,
        source_seat.id,
        target_seat.id,
        management_initiator,
    )

    assert isinstance(
        result.unwrap_err(), SeatChangeDeniedForBundledTicketError
    )
    assert _get_occupied_seat_id(bundled_ticket.id) == source_seat.id


def test_reject_move_from_group_seat(
    admin_app,
    party,
    category,
    make_area,
    make_group,
    make_seat,
    make_ticket,
    management_initiator,
):
    area = make_area()
    source_seat = make_seat(area, category)
    target_seat = make_seat(area, category)
    ticket = make_ticket(category, seat=source_seat)
    make_group(party, category, [source_seat])

    result = service.move_occupancy(
        area.id,
        source_seat.id,
        target_seat.id,
        management_initiator,
    )

    assert isinstance(result.unwrap_err(), SeatChangeDeniedForGroupSeatError)
    assert _get_occupied_seat_id(ticket.id) == source_seat.id


@pytest.mark.parametrize('blocked_position', ['source', 'target'])
def test_reject_swap_with_blocked_destination(
    admin_app,
    category,
    make_area,
    make_seat,
    make_ticket,
    management_initiator,
    blocked_position,
):
    area = make_area()
    source_seat = make_seat(area, category)
    target_seat = make_seat(area, category)
    source_ticket = make_ticket(category, seat=source_seat)
    target_ticket = make_ticket(category, seat=target_seat)
    blocked_seat = source_seat if blocked_position == 'source' else target_seat
    db.session.get(DbSeat, blocked_seat.id).blocked = True
    db.session.commit()

    result = service.swap_occupancies(
        area.id,
        source_seat.id,
        target_seat.id,
        management_initiator,
    )

    assert isinstance(result.unwrap_err(), SeatBlockedError)
    assert _get_occupied_seat_id(source_ticket.id) == source_seat.id
    assert _get_occupied_seat_id(target_ticket.id) == target_seat.id


@pytest.mark.parametrize('revoked_position', ['source', 'target'])
def test_reject_swap_with_revoked_ticket(
    admin_app,
    category,
    make_area,
    make_seat,
    make_ticket,
    management_initiator,
    revoked_position,
):
    area = make_area()
    source_seat = make_seat(area, category)
    target_seat = make_seat(area, category)
    source_ticket = make_ticket(category, seat=source_seat)
    target_ticket = make_ticket(category, seat=target_seat)
    revoked_ticket = (
        source_ticket if revoked_position == 'source' else target_ticket
    )
    revoked_ticket.revoked = True
    db.session.commit()

    result = service.swap_occupancies(
        area.id,
        source_seat.id,
        target_seat.id,
        management_initiator,
    )

    assert isinstance(result.unwrap_err(), TicketIsRevokedError)
    assert _get_occupied_seat_id(source_ticket.id) == source_seat.id
    assert _get_occupied_seat_id(target_ticket.id) == target_seat.id


@pytest.mark.parametrize('bundled_position', ['source', 'target'])
def test_reject_swap_with_bundled_ticket(
    admin_app,
    category,
    make_area,
    make_seat,
    make_ticket,
    management_initiator,
    ticket_owner,
    bundled_position,
):
    area = make_area()
    source_seat = make_seat(area, category)
    target_seat = make_seat(area, category)
    source_ticket = make_ticket(category, seat=source_seat)
    target_ticket = make_ticket(category, seat=target_seat)
    bundled_ticket = _make_bundled_ticket(category, ticket_owner)
    replaced_ticket = (
        source_ticket if bundled_position == 'source' else target_ticket
    )
    occupied_seat = source_seat if bundled_position == 'source' else target_seat
    replaced_ticket.occupied_seat_id = None
    bundled_ticket.occupied_seat_id = occupied_seat.id
    db.session.commit()

    result = service.swap_occupancies(
        area.id,
        source_seat.id,
        target_seat.id,
        management_initiator,
    )

    assert isinstance(
        result.unwrap_err(), SeatChangeDeniedForBundledTicketError
    )
    assert _get_occupied_seat_id(bundled_ticket.id) == occupied_seat.id


@pytest.mark.parametrize('grouped_position', ['source', 'target'])
def test_reject_swap_with_group_seat(
    admin_app,
    party,
    category,
    make_area,
    make_group,
    make_seat,
    make_ticket,
    management_initiator,
    grouped_position,
):
    area = make_area()
    source_seat = make_seat(area, category)
    target_seat = make_seat(area, category)
    source_ticket = make_ticket(category, seat=source_seat)
    target_ticket = make_ticket(category, seat=target_seat)
    grouped_seat = source_seat if grouped_position == 'source' else target_seat
    make_group(party, category, [grouped_seat])

    result = service.swap_occupancies(
        area.id,
        source_seat.id,
        target_seat.id,
        management_initiator,
    )

    assert isinstance(result.unwrap_err(), SeatChangeDeniedForGroupSeatError)
    assert _get_occupied_seat_id(source_ticket.id) == source_seat.id
    assert _get_occupied_seat_id(target_ticket.id) == target_seat.id


def test_reject_free_group_move_target(
    admin_app,
    party,
    category,
    make_area,
    make_group,
    make_seat,
    make_ticket,
    management_initiator,
):
    area = make_area()
    source_seat = make_seat(area, category)
    target_seat = make_seat(area, category)
    ticket = make_ticket(category, seat=source_seat)
    make_group(party, category, [target_seat])

    result = service.move_occupancy(
        area.id,
        source_seat.id,
        target_seat.id,
        management_initiator,
    )

    assert isinstance(result.unwrap_err(), SeatChangeDeniedForGroupSeatError)
    assert _get_occupied_seat_id(ticket.id) == source_seat.id


def test_reject_unknown_seat(
    admin_app,
    category,
    make_area,
    make_seat,
    make_ticket,
    management_initiator,
):
    area = make_area()
    source_seat = make_seat(area, category)
    ticket = make_ticket(category, seat=source_seat)
    unknown_seat_id = SeatID(generate_uuid())

    result = service.move_occupancy(
        area.id,
        source_seat.id,
        unknown_seat_id,
        management_initiator,
    )

    assert isinstance(result.unwrap_err(), SeatNotFoundError)
    assert _get_occupied_seat_id(ticket.id) == source_seat.id


def test_reject_unknown_seating_area(
    admin_app,
    category,
    make_area,
    make_seat,
    make_ticket,
    management_initiator,
):
    area = make_area()
    source_seat = make_seat(area, category)
    target_seat = make_seat(area, category)
    ticket = make_ticket(category, seat=source_seat)
    unknown_area_id = SeatingAreaID(generate_uuid())

    result = service.move_occupancy(
        unknown_area_id,
        source_seat.id,
        target_seat.id,
        management_initiator,
    )

    assert isinstance(result.unwrap_err(), SeatingAreaNotFoundError)
    assert _get_occupied_seat_id(ticket.id) == source_seat.id


def test_swap_failure_after_temporary_release_rolls_back_everything(
    admin_app,
    category,
    make_area,
    make_seat,
    make_ticket,
    management_initiator,
    monkeypatch,
):
    area = make_area()
    source_seat = make_seat(area, category)
    target_seat = make_seat(area, category)
    source_ticket = make_ticket(category, seat=source_seat)
    target_ticket = make_ticket(category, seat=target_seat)
    source_log_count = len(_get_log_entries(source_ticket.id))
    target_log_count = len(_get_log_entries(target_ticket.id))

    def fail_to_add_log(*args, **kwargs):
        raise RuntimeError('injected failure after temporary release')

    monkeypatch.setattr(service, '_add_occupy_log_entry', fail_to_add_log)

    with pytest.raises(RuntimeError, match='injected failure'):
        service.swap_occupancies(
            area.id,
            source_seat.id,
            target_seat.id,
            management_initiator,
        )

    assert _get_occupied_seat_id(source_ticket.id) == source_seat.id
    assert _get_occupied_seat_id(target_ticket.id) == target_seat.id
    assert len(_get_log_entries(source_ticket.id)) == source_log_count
    assert len(_get_log_entries(target_ticket.id)) == target_log_count


def test_swap_failure_after_first_log_rolls_back_without_partial_logs(
    admin_app,
    category,
    make_area,
    make_seat,
    make_ticket,
    management_initiator,
    monkeypatch,
):
    area = make_area()
    source_seat = make_seat(area, category)
    target_seat = make_seat(area, category)
    source_ticket = make_ticket(category, seat=source_seat)
    target_ticket = make_ticket(category, seat=target_seat)
    source_log_count = len(_get_log_entries(source_ticket.id))
    target_log_count = len(_get_log_entries(target_ticket.id))
    original_add_log = service._add_occupy_log_entry
    call_count = 0

    def fail_after_first_log(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError('injected failure after first log')
        original_add_log(*args, **kwargs)

    monkeypatch.setattr(service, '_add_occupy_log_entry', fail_after_first_log)

    with pytest.raises(RuntimeError, match='injected failure'):
        service.swap_occupancies(
            area.id,
            source_seat.id,
            target_seat.id,
            management_initiator,
        )

    assert _get_occupied_seat_id(source_ticket.id) == source_seat.id
    assert _get_occupied_seat_id(target_ticket.id) == target_seat.id
    assert len(_get_log_entries(source_ticket.id)) == source_log_count
    assert len(_get_log_entries(target_ticket.id)) == target_log_count


def test_move_commit_failure_rolls_back_flushed_assignment_and_log(
    admin_app,
    category,
    make_area,
    make_seat,
    make_ticket,
    management_initiator,
    monkeypatch,
):
    area = make_area()
    source_seat = make_seat(area, category)
    target_seat = make_seat(area, category)
    ticket = make_ticket(category, seat=source_seat)
    previous_log_count = len(_get_log_entries(ticket.id))

    def fail_commit():
        raise RuntimeError('injected commit failure')

    with monkeypatch.context() as context:
        context.setattr(db.session, 'commit', fail_commit)
        with pytest.raises(RuntimeError, match='injected commit failure'):
            service.move_occupancy(
                area.id,
                source_seat.id,
                target_seat.id,
                management_initiator,
            )

    assert _get_occupied_seat_id(ticket.id) == source_seat.id
    assert len(_get_log_entries(ticket.id)) == previous_log_count


def test_recognized_unique_conflict_rolls_back_and_keeps_session_usable(
    admin_app,
    category,
    make_area,
    make_seat,
    make_ticket,
    management_initiator,
    monkeypatch,
):
    area = make_area()
    source_seat = make_seat(area, category)
    target_seat = make_seat(area, category)
    source_ticket = make_ticket(category, seat=source_seat)
    competing_ticket = make_ticket(category)
    previous_log_count = len(_get_log_entries(source_ticket.id))
    original_add_log = service._add_occupy_log_entry

    def add_conflicting_occupancy(*args, **kwargs):
        competing_ticket.occupied_seat_id = target_seat.id
        original_add_log(*args, **kwargs)

    monkeypatch.setattr(
        service, '_add_occupy_log_entry', add_conflicting_occupancy
    )

    result = service.move_occupancy(
        area.id,
        source_seat.id,
        target_seat.id,
        management_initiator,
    )

    assert isinstance(result.unwrap_err(), ConcurrentSeatChangeError)
    assert _get_occupied_seat_id(source_ticket.id) == source_seat.id
    assert _get_occupied_seat_id(competing_ticket.id) is None
    assert len(_get_log_entries(source_ticket.id)) == previous_log_count
    assert db.session.scalar(db.select(db.literal(1))) == 1


def _make_bundled_ticket(category, owner) -> DbTicket:
    bundle = ticket_bundle_service.create_bundle(category, 1, owner)
    return ticket_service.get_ticket(bundle.ticket_ids[0])


def _get_occupied_seat_id(ticket_id):
    db.session.expire_all()
    db_ticket = db.session.get(DbTicket, ticket_id)
    assert db_ticket is not None
    return db_ticket.occupied_seat_id


def _get_blocked(seat_id):
    db.session.expire_all()
    db_seat = db.session.get(DbSeat, seat_id)
    assert db_seat is not None
    return db_seat.blocked


def _get_log_entries(ticket_id):
    db.session.expire_all()
    return ticket_log_service.get_entries_for_ticket(ticket_id)
