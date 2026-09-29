"""
:License: Revised BSD (see `LICENSE` file for details)
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from byceps.database import db
from byceps.services.chair_optout import chair_optout_service
from byceps.services.chair_optout.dbmodels import DbPartyTicketChairOptout
from byceps.services.seating import seat_service, seating_area_service
from byceps.services.ticketing import (
    ticket_creation_service,
    ticket_seat_management_service,
    ticket_service,
    ticket_user_management_service,
)
from byceps.services.ticketing.dbmodels.ticket import DbTicket
from byceps.services.ticketing.log import ticket_log_domain_service

from tests.helpers import generate_token


def test_answer_without_seat_is_reported(
    admin_app, party, user, make_ticket_category
):
    category = make_ticket_category(party.id, generate_token())
    ticket = ticket_creation_service.create_ticket(category, user, user=user)

    answer = chair_optout_service.set_optout(
        party.id, ticket.id, user.id, False
    )
    entries = chair_optout_service.get_report_entries_for_party(party.id)

    assert answer.brings_own_chair is False
    entry = next(entry for entry in entries if entry.ticket_id == ticket.id)
    assert entry.has_seat is False
    assert entry.brings_own_chair is False


def test_repeated_save_updates_same_row(
    admin_app, party, user, make_ticket_category
):
    category = make_ticket_category(party.id, generate_token())
    ticket = ticket_creation_service.create_ticket(category, user, user=user)

    first = chair_optout_service.set_optout(party.id, ticket.id, user.id, True)
    second = chair_optout_service.set_optout(
        party.id, ticket.id, user.id, False
    )

    assert first.id == second.id
    assert second.brings_own_chair is False
    assert (
        db.session.scalar(
            select(func.count())
            .select_from(DbPartyTicketChairOptout)
            .filter_by(party_id=party.id, ticket_id=ticket.id)
        )
        == 1
    )


def test_unanswered_ticket_prompt_clears_after_answer(
    admin_app, party, make_user, make_ticket_category
):
    participant = make_user(generate_token())
    category = make_ticket_category(party.id, generate_token())
    ticket = ticket_creation_service.create_ticket(
        category, participant, user=participant
    )

    assert (
        chair_optout_service.find_first_unanswered_ticket_id_for_user(
            party.id, participant.id
        )
        == ticket.id
    )

    chair_optout_service.set_optout(party.id, ticket.id, participant.id, False)

    assert (
        chair_optout_service.find_first_unanswered_ticket_id_for_user(
            party.id, participant.id
        )
        is None
    )


def test_seat_change_preserves_answer(
    admin_app, party, user, make_ticket_category
):
    category = make_ticket_category(party.id, generate_token())
    area = seating_area_service.create_area(
        party.id, generate_token(), generate_token()
    )
    first_seat = seat_service.create_seat(
        area.id, 1, 2, category.id, label='A-1'
    )
    second_seat = seat_service.create_seat(
        area.id, 3, 4, category.id, label='B-2'
    )
    ticket = ticket_creation_service.create_ticket(category, user, user=user)
    chair_optout_service.set_optout(party.id, ticket.id, user.id, True)

    ticket_seat_management_service.occupy_seat(
        ticket.id, first_seat.id, user
    ).unwrap()
    ticket_seat_management_service.occupy_seat(
        ticket.id, second_seat.id, user
    ).unwrap()

    answer = chair_optout_service.get_optout(party.id, ticket.id)
    assert answer is not None
    assert answer.brings_own_chair is True


def test_reassignment_invalidates_and_replaces_previous_answer(
    admin_app, party, user, make_user, make_ticket_category
):
    new_user = make_user(generate_token())
    category = make_ticket_category(party.id, generate_token())
    ticket = ticket_creation_service.create_ticket(category, user, user=user)
    chair_optout_service.set_optout(party.id, ticket.id, user.id, True)

    ticket_user_management_service.appoint_user(
        ticket.id, new_user, user
    ).unwrap()

    assert chair_optout_service.get_optout(party.id, ticket.id) is None
    entry = next(
        entry
        for entry in chair_optout_service.get_report_entries_for_party(party.id)
        if entry.ticket_id == ticket.id
    )
    assert entry.brings_own_chair is None

    answer = chair_optout_service.set_optout(
        party.id, ticket.id, new_user.id, False
    )
    assert answer.user_id == new_user.id
    assert answer.brings_own_chair is False


def test_set_answer_enforces_party_boundary(
    admin_app, party, brand, user, make_party, make_ticket_category
):
    other_party = make_party(brand, title=generate_token())
    category = make_ticket_category(party.id, generate_token())
    ticket = ticket_creation_service.create_ticket(category, user, user=user)

    with pytest.raises(ValueError):
        chair_optout_service.set_optout(
            other_party.id, ticket.id, user.id, True
        )


@pytest.mark.parametrize('withdraw', [False, True])
def test_returning_participant_must_answer_again(
    admin_app, party, user, make_user, make_ticket_category, withdraw
):
    category = make_ticket_category(party.id, generate_token())
    ticket = ticket_creation_service.create_ticket(category, user, user=user)
    chair_optout_service.set_optout(party.id, ticket.id, user.id, True)
    if withdraw:
        ticket_user_management_service.withdraw_user(ticket.id, user).unwrap()
    else:
        other_user = make_user(generate_token())
        ticket_user_management_service.appoint_user(
            ticket.id, other_user, user
        ).unwrap()
    ticket_user_management_service.appoint_user(ticket.id, user, user).unwrap()

    assert chair_optout_service.get_optout(party.id, ticket.id) is None
    entries = chair_optout_service.get_report_entries_for_party(party.id)
    entry = next(entry for entry in entries if entry.ticket_id == ticket.id)
    assert entry.brings_own_chair is None
    assert ticket.id not in {
        answer.ticket_id
        for answer in chair_optout_service.list_optouts_for_user(
            party.id, user.id
        )
    }

    chair_optout_service.set_optout(party.id, ticket.id, user.id, False)
    answer = chair_optout_service.get_optout(party.id, ticket.id)
    assert answer.brings_own_chair is False


def test_save_locks_ticket_until_answer_is_committed(
    admin_app, party, user, make_ticket_category, monkeypatch
):
    category = make_ticket_category(party.id, generate_token())
    ticket = ticket_creation_service.create_ticket(category, user, user=user)
    ticket_id = ticket.id
    find_eligible = chair_optout_service._find_eligible_ticket

    def verify_lock(*args):
        result = find_eligible(*args)
        with Session(db.engine) as concurrent:
            with pytest.raises(OperationalError) as error:
                concurrent.execute(
                    select(DbTicket)
                    .filter_by(id=ticket_id)
                    .with_for_update(nowait=True)
                )
            assert error.value.orig.sqlstate == '55P03'
        return result

    monkeypatch.setattr(
        chair_optout_service, '_find_eligible_ticket', verify_lock
    )
    chair_optout_service.set_optout(party.id, ticket_id, user.id, True)
    with Session(db.engine) as concurrent:
        assert (
            concurrent.scalar(
                select(DbTicket)
                .filter_by(id=ticket_id)
                .with_for_update(nowait=True)
            )
            is not None
        )


def test_save_refreshes_previously_loaded_answer(
    admin_app, party, user, make_ticket_category
):
    category = make_ticket_category(party.id, generate_token())
    ticket = ticket_creation_service.create_ticket(category, user, user=user)
    first = chair_optout_service.set_optout(party.id, ticket.id, user.id, True)
    loaded = db.session.get(DbPartyTicketChairOptout, first.id)
    assert loaded.brings_own_chair is True
    answer = chair_optout_service.set_optout(
        party.id, ticket.id, user.id, False
    )
    assert answer.brings_own_chair is False


def test_parallel_first_answers_create_one_row(
    admin_app, party, user, make_ticket_category
):
    category = make_ticket_category(party.id, generate_token())
    ticket = ticket_creation_service.create_ticket(category, user, user=user)
    party_id, ticket_id, user_id = party.id, ticket.id, user.id
    barrier = Barrier(2)

    def save(value):
        with admin_app.app_context():
            db.session.execute(text("SET LOCAL lock_timeout = '5s'"))
            barrier.wait(timeout=5)
            return chair_optout_service.set_optout(
                party_id, ticket_id, user_id, value
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(save, value) for value in (True, False)]
        answers = [future.result(timeout=10) for future in futures]

    assert answers[0].id == answers[1].id
    assert [answer.brings_own_chair for answer in answers] == [True, False]
    with Session(db.engine) as independent:
        rows = independent.scalars(
            select(DbPartyTicketChairOptout).filter_by(ticket_id=ticket_id)
        ).all()
        assert len(rows) == 1


@pytest.mark.parametrize('revoke', [False, True])
def test_save_rechecks_ticket_after_concurrent_change(
    admin_app, party, user, make_user, make_ticket_category, revoke
):
    category = make_ticket_category(party.id, generate_token())
    new_user = make_user(generate_token())
    ticket = ticket_creation_service.create_ticket(category, user, user=user)
    ticket_id = ticket.id
    assert ticket.used_by_id == user.id
    with Session(db.engine) as independent:
        values = {'revoked': True} if revoke else {'used_by_id': new_user.id}
        independent.execute(
            update(DbTicket).where(DbTicket.id == ticket_id).values(**values)
        )
        independent.commit()

    with pytest.raises(ValueError):
        chair_optout_service.set_optout(party.id, ticket_id, user.id, True)
    with Session(db.engine) as independent:
        assert (
            independent.scalar(
                select(DbPartyTicketChairOptout).filter_by(ticket_id=ticket_id)
            )
            is None
        )


def test_failed_commit_preserves_answer_and_releases_ticket_lock(
    admin_app, party, user, make_ticket_category, monkeypatch
):
    category = make_ticket_category(party.id, generate_token())
    ticket = ticket_creation_service.create_ticket(category, user, user=user)
    ticket_id = ticket.id
    chair_optout_service.set_optout(party.id, ticket_id, user.id, True)

    def fail_commit():
        raise RuntimeError('Simulated commit failure')

    with monkeypatch.context() as patch:
        patch.setattr(db.session, 'commit', fail_commit)
        with pytest.raises(RuntimeError, match='Simulated commit failure'):
            chair_optout_service.set_optout(party.id, ticket_id, user.id, False)

    with Session(db.engine) as independent:
        independent.execute(
            select(DbTicket)
            .filter_by(id=ticket_id)
            .with_for_update(nowait=True)
        )
        answer = independent.scalar(
            select(DbPartyTicketChairOptout).filter_by(ticket_id=ticket_id)
        )
        assert answer.brings_own_chair is True


def test_reassignment_invalidates_answer_saved_after_audit_entry_creation(
    admin_app, party, user, make_user, make_ticket_category, monkeypatch
):
    category = make_ticket_category(party.id, generate_token())
    new_user = make_user(generate_token())
    ticket = ticket_creation_service.create_ticket(category, user, user=user)
    ticket_id, party_id, user_id = ticket.id, party.id, user.id
    audit_created = Event()
    allow_commit = Event()
    build_entry = ticket_log_domain_service.build_user_appointed_entry

    def pause_after_audit_entry(*args):
        entry = build_entry(*args)
        audit_created.set()
        assert allow_commit.wait(timeout=10)
        return entry

    def reassign():
        with admin_app.app_context():
            db.session.execute(text("SET LOCAL lock_timeout = '5s'"))
            ticket_user_management_service.appoint_user(
                ticket_id, new_user, user
            ).unwrap()

    with monkeypatch.context() as patch:
        patch.setattr(
            ticket_log_domain_service,
            'build_user_appointed_entry',
            pause_after_audit_entry,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(reassign)
            try:
                assert audit_created.wait(timeout=5)
                chair_optout_service.set_optout(
                    party_id, ticket_id, user_id, True
                )
            finally:
                allow_commit.set()
            future.result(timeout=10)

    db.session.expire_all()
    ticket_user_management_service.appoint_user(ticket_id, user, user).unwrap()
    assert chair_optout_service.get_optout(party_id, ticket_id) is None


def test_reappointing_same_participant_preserves_answer(
    admin_app, party, user, make_ticket_category
):
    category = make_ticket_category(party.id, generate_token())
    ticket = ticket_creation_service.create_ticket(category, user, user=user)
    chair_optout_service.set_optout(party.id, ticket.id, user.id, True)
    ticket_user_management_service.appoint_user(ticket.id, user, user).unwrap()
    assert chair_optout_service.get_optout(party.id, ticket.id) is not None


def test_delayed_duplicate_appointment_preserves_new_participants_answer(
    admin_app, party, user, make_user, make_ticket_category, monkeypatch
):
    category = make_ticket_category(party.id, generate_token())
    new_user = make_user(generate_token())
    ticket = ticket_creation_service.create_ticket(category, user, user=user)
    ticket_id, party_id = ticket.id, party.id
    first_prepared = Event()
    allow_commit = Event()
    build_entry = ticket_log_domain_service.build_user_appointed_entry

    def pause_first_appointment(*args):
        entry = build_entry(*args)
        if not first_prepared.is_set():
            first_prepared.set()
            assert allow_commit.wait(timeout=10)
        return entry

    def appoint():
        with admin_app.app_context():
            db.session.execute(text("SET LOCAL lock_timeout = '5s'"))
            ticket_user_management_service.appoint_user(
                ticket_id, new_user, user
            ).unwrap()

    monkeypatch.setattr(
        ticket_log_domain_service,
        'build_user_appointed_entry',
        pause_first_appointment,
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(appoint)
        try:
            assert first_prepared.wait(timeout=5)
            ticket_user_management_service.appoint_user(
                ticket_id, new_user, user
            ).unwrap()
            chair_optout_service.set_optout(
                party_id, ticket_id, new_user.id, True
            )
        finally:
            allow_commit.set()
        future.result(timeout=10)

    db.session.expire_all()
    answer = chair_optout_service.get_optout(party_id, ticket_id)
    assert answer is not None
    assert answer.user_id == new_user.id
    assert answer.brings_own_chair is True


@pytest.mark.parametrize('value', [False, True])
def test_deleting_ticket_removes_dependent_answer(
    admin_app, party, user, make_ticket_category, value
):
    category = make_ticket_category(party.id, generate_token())
    ticket = ticket_creation_service.create_ticket(category, user, user=user)
    ticket_id = ticket.id
    chair_optout_service.set_optout(party.id, ticket_id, user.id, value)
    ticket_service.delete_ticket(ticket_id)
    with Session(db.engine) as independent:
        assert independent.get(DbTicket, ticket_id) is None
        assert (
            independent.scalar(
                select(DbPartyTicketChairOptout).filter_by(ticket_id=ticket_id)
            )
            is None
        )


def test_rollback_of_participant_change_restores_answer(
    admin_app, party, user, make_user, make_ticket_category
):
    category = make_ticket_category(party.id, generate_token())
    new_user = make_user(generate_token())
    ticket = ticket_creation_service.create_ticket(category, user, user=user)
    ticket_id, party_id = ticket.id, party.id
    chair_optout_service.set_optout(party_id, ticket_id, user.id, True)
    ticket.used_by_id = new_user.id
    db.session.flush()
    assert chair_optout_service.get_optout(party_id, ticket_id) is None
    db.session.rollback()
    assert chair_optout_service.get_optout(party_id, ticket_id) is not None
