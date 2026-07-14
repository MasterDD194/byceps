"""
:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

from byceps.database import db
from byceps.services.seating.management import service
from byceps.services.seating.management.errors import (
    ConcurrentSeatChangeError,
)
from byceps.services.ticketing import ticket_seat_management_service
from byceps.services.ticketing.dbmodels.ticket import DbTicket
from byceps.services.ticketing.log import ticket_log_service


def test_concurrent_moves_to_same_target_detect_changed_occupancy(
    admin_app,
    category,
    make_area,
    make_seat,
    make_ticket,
    management_initiator,
    monkeypatch,
):
    area = make_area()
    source_seat1 = make_seat(area, category)
    source_seat2 = make_seat(area, category)
    target_seat = make_seat(area, category)
    ticket1 = make_ticket(category, seat=source_seat1)
    ticket2 = make_ticket(category, seat=source_seat2)
    ticket1_log_count = len(
        ticket_log_service.get_entries_for_ticket(ticket1.id)
    )
    ticket2_log_count = len(
        ticket_log_service.get_entries_for_ticket(ticket2.id)
    )

    original_lock_seats = service._lock_seats_for_update
    both_baselines_read = Barrier(2)

    def synchronized_lock(seat_ids):
        both_baselines_read.wait(timeout=10)
        return original_lock_seats(seat_ids)

    monkeypatch.setattr(service, '_lock_seats_for_update', synchronized_lock)

    def move(source_seat_id):
        with admin_app.app_context():
            return service.move_occupancy(
                area.id,
                source_seat_id,
                target_seat.id,
                management_initiator,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        future1 = executor.submit(move, source_seat1.id)
        future2 = executor.submit(move, source_seat2.id)
        result1 = future1.result(timeout=20)
        result2 = future2.result(timeout=20)

    assert sum(result.is_ok() for result in (result1, result2)) == 1
    errors = [
        result.unwrap_err() for result in (result1, result2) if result.is_err()
    ]
    assert len(errors) == 1
    assert isinstance(errors[0], ConcurrentSeatChangeError)

    db.session.expire_all()
    occupied_seat_ids = {
        db.session.get(DbTicket, ticket1.id).occupied_seat_id,
        db.session.get(DbTicket, ticket2.id).occupied_seat_id,
    }
    assert target_seat.id in occupied_seat_ids
    assert source_seat1.id in occupied_seat_ids or source_seat2.id in (
        occupied_seat_ids
    )

    added_log_count = (
        len(ticket_log_service.get_entries_for_ticket(ticket1.id))
        - ticket1_log_count
        + len(ticket_log_service.get_entries_for_ticket(ticket2.id))
        - ticket2_log_count
    )
    assert added_log_count == 1


def test_source_release_after_baseline_is_detected(
    admin_app,
    category,
    make_area,
    make_seat,
    make_ticket,
    management_initiator,
    monkeypatch,
    ticket_owner,
):
    area = make_area()
    source_seat = make_seat(area, category)
    target_seat = make_seat(area, category)
    ticket = make_ticket(category, seat=source_seat)
    previous_log_count = len(
        ticket_log_service.get_entries_for_ticket(ticket.id)
    )
    baseline_read = Event()
    continue_locking = Event()
    original_lock_tickets = service._lock_tickets_for_update

    def delayed_ticket_lock(ticket_ids):
        baseline_read.set()
        assert continue_locking.wait(timeout=10)
        return original_lock_tickets(ticket_ids)

    monkeypatch.setattr(
        service, '_lock_tickets_for_update', delayed_ticket_lock
    )

    def move():
        with admin_app.app_context():
            return service.move_occupancy(
                area.id,
                source_seat.id,
                target_seat.id,
                management_initiator,
            )

    with ThreadPoolExecutor(max_workers=1) as executor:
        move_future = executor.submit(move)
        assert baseline_read.wait(timeout=10)
        try:
            release_result = ticket_seat_management_service.release_seat(
                ticket.id, ticket_owner
            )
            assert release_result.is_ok()
        finally:
            continue_locking.set()

        move_result = move_future.result(timeout=20)

    assert isinstance(move_result.unwrap_err(), ConcurrentSeatChangeError)
    db.session.expire_all()
    db_ticket = db.session.get(DbTicket, ticket.id)
    assert db_ticket is not None
    assert db_ticket.occupied_seat_id is None
    assert (
        len(ticket_log_service.get_entries_for_ticket(ticket.id))
        == previous_log_count + 1
    )
