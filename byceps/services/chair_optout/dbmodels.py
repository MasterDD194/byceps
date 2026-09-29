"""
byceps.services.chair_optout.dbmodels
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:License: Revised BSD (see `LICENSE` file for details)
"""

from datetime import datetime

from sqlalchemy import delete, event, inspect
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, mapped_column, Mapper

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.ticketing.dbmodels.ticket import DbTicket
from byceps.services.ticketing.models.ticket import TicketID
from byceps.services.user.models import UserID
from byceps.util.uuid import generate_uuid7

from .models import ChairOptoutID


class DbPartyTicketChairOptout(db.Model):  # type: ignore[name-defined]
    """The chair opt-out setting for a party ticket."""

    __tablename__ = 'party_ticket_chair_optouts'
    __table_args__ = (db.UniqueConstraint('party_id', 'ticket_id'),)

    id: Mapped[ChairOptoutID] = mapped_column(
        db.Uuid, default=generate_uuid7, primary_key=True
    )
    party_id: Mapped[PartyID] = mapped_column(
        db.UnicodeText, db.ForeignKey('parties.id'), index=True
    )
    ticket_id: Mapped[TicketID] = mapped_column(
        db.Uuid, db.ForeignKey('tickets.id', ondelete='CASCADE'), index=True
    )
    user_id: Mapped[UserID] = mapped_column(
        db.Uuid, db.ForeignKey('users.id'), index=True
    )
    brings_own_chair: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime]

    def __init__(
        self,
        party_id: PartyID,
        ticket_id: TicketID,
        user_id: UserID,
        updated_at: datetime,
        *,
        brings_own_chair: bool = False,
    ) -> None:
        self.party_id = party_id
        self.ticket_id = ticket_id
        self.user_id = user_id
        self.brings_own_chair = brings_own_chair
        self.updated_at = updated_at


@event.listens_for(DbTicket, 'after_update')
def _clear_answer_after_participant_change(
    mapper: Mapper, connection: Connection, ticket: DbTicket
) -> None:
    """Invalidate answers in the same transaction as Ticketing's ORM update.

    Audit entry timestamps are assigned before commit, so they cannot safely
    determine whether a concurrent participant change followed an answer.
    """
    if inspect(ticket).attrs.used_by_id.history.has_changes():
        connection.execute(
            delete(DbPartyTicketChairOptout).where(
                DbPartyTicketChairOptout.ticket_id == ticket.id,
                # A stale duplicate appointment may observe a change in ORM
                # history even when this participant is already current.
                DbPartyTicketChairOptout.user_id != ticket.used_by_id,
            )
        )
