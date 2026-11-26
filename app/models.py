from __future__ import annotations

import reflex as rx

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class ResearchChat(Base):
    __tablename__ = "research_chat"
    __table_args__ = (
        UniqueConstraint("id", "owner_sub", name="uq_research_chat_id_owner"),
        CheckConstraint("length(btrim(owner_sub)) > 0", name="owner_required"),
        CheckConstraint("updated_at >= created_at", name="timestamp_order"),
        Index(
            "ix_research_chat_owner_updated", "owner_sub", "updated_at", "id"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_sub: Mapped[str] = mapped_column(Text, default="", server_default="")
    title: Mapped[str] = mapped_column(
        Text, default="Untitled research", server_default="Untitled research"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="chat",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="(ChatMessage.created_at, ChatMessage.id)",
    )
    selections: Mapped[list[SavedSelection]] = relationship(
        back_populates="research_chat",
        foreign_keys="SavedSelection.research_chat_id",
    )


class ChatMessage(Base):
    __tablename__ = "chat_message"
    __table_args__ = (
        CheckConstraint(
            "role IN ('system', 'user', 'assistant', 'tool')", name="valid_role"
        ),
        CheckConstraint(
            "jsonb_typeof(evidence_metadata) = 'object'", name="evidence_object"
        ),
        CheckConstraint(
            "jsonb_typeof(source_metadata) = 'array'", name="sources_array"
        ),
        CheckConstraint("updated_at >= created_at", name="timestamp_order"),
        Index("ix_chat_message_chat_created", "chat_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    chat_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("research_chat.id", ondelete="CASCADE"),
        default=uuid4,
    )
    role: Mapped[str] = mapped_column(
        String(16), default="user", server_default="user"
    )
    content: Mapped[str] = mapped_column(Text, default="", server_default="")
    evidence_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        comment="Evidence claims, explicit gaps, freshness and methodology; never credentials.",
    )
    source_metadata: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        comment="Source URL, publisher, title, published/observed time and claim references.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    chat: Mapped[ResearchChat] = relationship(back_populates="messages")


class SavedSelection(Base):
    __tablename__ = "saved_selection"
    __table_args__ = (
        ForeignKeyConstraint(
            ["research_chat_id", "owner_sub"],
            ["research_chat.id", "research_chat.owner_sub"],
            name="fk_saved_selection_chat_owner",
            ondelete="RESTRICT",
        ),
        CheckConstraint("length(btrim(owner_sub)) > 0", name="owner_required"),
        CheckConstraint(
            "bookmaker IN ('SportyBet', 'Bet9ja', 'BetKing')",
            name="valid_bookmaker",
        ),
        CheckConstraint(
            "data_status IN ('sample', 'manual', 'verified')",
            name="valid_status",
        ),
        CheckConstraint(
            "is_sample = (data_status = 'sample')",
            name="sample_status_consistent",
        ),
        CheckConstraint(
            "NOT (is_sample AND is_live)", name="sample_never_live"
        ),
        CheckConstraint(
            "decimal_odds IS NULL OR decimal_odds > 1",
            name="valid_decimal_odds",
        ),
        CheckConstraint(
            "decimal_odds IS NULL OR observed_at IS NOT NULL",
            name="odds_observation_required",
        ),
        CheckConstraint(
            "jsonb_typeof(evidence_provenance) = 'object'",
            name="provenance_object",
        ),
        CheckConstraint(
            "data_status != 'verified' OR (observed_at IS NOT NULL "
            "AND length(btrim(source_provider)) > 0 AND length(btrim(source_url)) > 0 "
            "AND evidence_provenance != '{}'::jsonb)",
            name="verified_evidence_required",
        ),
        CheckConstraint("updated_at >= created_at", name="timestamp_order"),
        Index(
            "ix_saved_selection_owner_created", "owner_sub", "created_at", "id"
        ),
        Index("ix_saved_selection_chat_owner", "research_chat_id", "owner_sub"),
        Index(
            "ix_saved_selection_event_market",
            "owner_sub",
            "canonical_event_id",
            "market_key",
            "market_period",
        ),
        Index(
            "ix_saved_selection_bookmaker_observed",
            "owner_sub",
            "bookmaker",
            "observed_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_sub: Mapped[str] = mapped_column(Text, default="", server_default="")
    research_chat_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    sport: Mapped[str] = mapped_column(
        String(32), default="football", server_default="football"
    )
    event_name: Mapped[str] = mapped_column(Text, default="", server_default="")
    competition: Mapped[str] = mapped_column(
        Text, default="", server_default=""
    )
    home_team: Mapped[str] = mapped_column(Text, default="", server_default="")
    away_team: Mapped[str] = mapped_column(Text, default="", server_default="")
    kickoff_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    canonical_event_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    market_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    market_name: Mapped[str] = mapped_column(
        Text, default="", server_default=""
    )
    market_period: Mapped[str] = mapped_column(
        Text, default="match", server_default="match"
    )
    outcome_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome_name: Mapped[str] = mapped_column(
        Text, default="", server_default=""
    )
    line: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    line_label: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Exact operator label, including split lines.",
    )
    subject_name: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Team or player when applicable."
    )
    settlement_rules: Mapped[str | None] = mapped_column(Text, nullable=True)
    card_definition: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Cards versus booking points, red-card treatment and exclusions.",
    )
    bookmaker: Mapped[str] = mapped_column(
        String(16), default="SportyBet", server_default="SportyBet"
    )
    bookmaker_country: Mapped[str] = mapped_column(
        String(2), default="NG", server_default="NG"
    )
    decimal_odds: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 6), nullable=True
    )
    data_status: Mapped[str] = mapped_column(
        String(16), default="manual", server_default="manual"
    )
    is_sample: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    is_live: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
        comment="In-play observation, not a verification or freshness claim.",
    )
    observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_provider: Mapped[str] = mapped_column(
        Text, default="", server_default=""
    )
    source_url: Mapped[str] = mapped_column(Text, default="", server_default="")
    source_event_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_market_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_outcome_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    bookmaker_event_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    bookmaker_market_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    bookmaker_outcome_id: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    bookmaker_event_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Only documented operator/provider links; not synthetic booking codes.",
    )
    evidence_provenance: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        comment="Evidence references, verified feed identity, observation context and mapping/settlement gaps.",
    )
    research_rationale: Mapped[str] = mapped_column(
        Text, default="", server_default=""
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    research_chat: Mapped[ResearchChat | None] = relationship(
        back_populates="selections",
        foreign_keys=[research_chat_id],
    )
