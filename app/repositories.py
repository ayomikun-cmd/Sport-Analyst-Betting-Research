import reflex as rx

from datetime import datetime, timezone
from uuid import UUID

from reflex_enterprise.auth import User
from sqlalchemy import select

from app.models import ChatMessage, ResearchChat, SavedSelection
from app.research_service import (
    ChatView,
    MessageView,
    ResearchResult,
    source_records,
)


async def current_owner() -> str:
    claims = await User.current() or {}
    owner = claims.get("sub", "")
    if not isinstance(owner, str) or not owner.strip():
        raise PermissionError("Sign in to access private research.")
    return owner


def owned_messages_statement(chat_id: UUID, owner: str):
    return (
        select(ChatMessage)
        .join(ResearchChat, ChatMessage.chat_id == ResearchChat.id)
        .where(ResearchChat.id == chat_id, ResearchChat.owner_sub == owner)
        .order_by(ChatMessage.created_at, ChatMessage.id)
    )


def message_view(row: ChatMessage) -> MessageView:
    evidence = row.evidence_metadata or {}
    gaps = evidence.get("gaps", [])
    return {
        "id": str(row.id),
        "role": row.role,
        "content": row.content,
        "sources": source_records(row.source_metadata or []),
        "gaps": [str(gap) for gap in gaps] if isinstance(gaps, list) else [],
        "status": str(evidence.get("status", "unverified")),
        "researched_at": str(evidence.get("researched_at", "")),
    }


async def list_chats() -> list[ChatView]:
    owner = await current_owner()
    async with rx.asession() as session:
        rows = (
            await session.scalars(
                select(ResearchChat)
                .where(ResearchChat.owner_sub == owner)
                .order_by(
                    ResearchChat.updated_at.desc(), ResearchChat.id.desc()
                )
            )
        ).all()
        return [
            {
                "id": str(row.id),
                "title": row.title,
                "updated": row.updated_at.astimezone(timezone.utc).strftime(
                    "%d %b · %H:%M UTC"
                ),
            }
            for row in rows
        ]


async def load_messages(chat_id: str) -> list[MessageView]:
    owner = await current_owner()
    identity = UUID(chat_id)
    async with rx.asession() as session:
        chat = await session.scalar(
            select(ResearchChat).where(
                ResearchChat.id == identity, ResearchChat.owner_sub == owner
            )
        )
        if chat is None:
            raise PermissionError("Research not available.")
        rows = (
            await session.scalars(owned_messages_statement(identity, owner))
        ).all()
        return [message_view(row) for row in rows]


async def save_prompt(
    chat_id: str, prompt: str, status: str
) -> tuple[str, MessageView]:
    owner = await current_owner()
    async with rx.asession() as session:
        if chat_id:
            chat = await session.scalar(
                select(ResearchChat)
                .where(
                    ResearchChat.id == UUID(chat_id),
                    ResearchChat.owner_sub == owner,
                )
                .with_for_update()
            )
            if chat is None:
                raise PermissionError("Research not available.")
        else:
            chat = ResearchChat(
                owner_sub=owner, title=" ".join(prompt.split())[:90]
            )
            session.add(chat)
            await session.flush()
        chat.updated_at = datetime.now(timezone.utc)
        row = ChatMessage(
            chat_id=chat.id,
            role="user",
            content=prompt,
            evidence_metadata={
                "status": status,
                "context": "unverified user context",
            },
        )
        session.add(row)
        await session.flush()
        view = message_view(row)
        identity = str(chat.id)
        await session.commit()
        return identity, view


async def save_reply(chat_id: str, result: ResearchResult) -> MessageView:
    owner = await current_owner()
    async with rx.asession() as session:
        chat = await session.scalar(
            select(ResearchChat)
            .where(
                ResearchChat.id == UUID(chat_id),
                ResearchChat.owner_sub == owner,
            )
            .with_for_update()
        )
        if chat is None:
            raise PermissionError("Research not available.")
        chat.updated_at = datetime.now(timezone.utc)
        row = ChatMessage(
            chat_id=chat.id,
            role="assistant",
            content=result["content"],
            source_metadata=source_records(result["sources"]),
            evidence_metadata={
                "status": result["status"],
                "gaps": result["gaps"],
                "researched_at": result["researched_at"],
                "freshness": "Research time is not source publication time; review dated evidence.",
                "verification": "AI-retrieved evidence, not independently verified by the app",
            },
        )
        session.add(row)
        await session.flush()
        view = message_view(row)
        await session.commit()
        return view


async def list_saved_selections() -> list[SavedSelection]:
    owner = await current_owner()
    async with rx.asession() as session:
        return list(
            (
                await session.scalars(
                    select(SavedSelection)
                    .where(SavedSelection.owner_sub == owner)
                    .order_by(SavedSelection.created_at.desc())
                )
            ).all()
        )


async def get_saved_selection(selection_id: str) -> SavedSelection:
    owner = await current_owner()
    async with rx.asession() as session:
        row = await session.scalar(
            select(SavedSelection).where(
                SavedSelection.id == UUID(selection_id),
                SavedSelection.owner_sub == owner,
            )
        )
        if row is None:
            raise PermissionError("Selection not available.")
        return row


async def save_selection(
    selection: SavedSelection, selection_id: str = ""
) -> str:
    owner = await current_owner()
    async with rx.asession() as session:
        if selection.research_chat_id:
            chat = await session.scalar(
                select(ResearchChat).where(
                    ResearchChat.id == selection.research_chat_id,
                    ResearchChat.owner_sub == owner,
                )
            )
            if chat is None:
                raise PermissionError("Research not available.")
        if selection_id:
            row = await session.scalar(
                select(SavedSelection)
                .where(
                    SavedSelection.id == UUID(selection_id),
                    SavedSelection.owner_sub == owner,
                )
                .with_for_update()
            )
            if row is None:
                raise PermissionError("Selection not available.")
            for column in SavedSelection.__table__.columns:
                if column.name not in {
                    "id",
                    "owner_sub",
                    "created_at",
                    "updated_at",
                }:
                    setattr(row, column.name, getattr(selection, column.name))
        else:
            values = {
                column.name: getattr(selection, column.name)
                for column in SavedSelection.__table__.columns
                if column.name
                not in {"id", "owner_sub", "created_at", "updated_at"}
                and getattr(selection, column.name) is not None
            }
            row = SavedSelection(owner_sub=owner, **values)
            session.add(row)
        await session.flush()
        identity = str(row.id)
        await session.commit()
        return identity


async def delete_saved_selection(selection_id: str):
    owner = await current_owner()
    async with rx.asession() as session:
        row = await session.scalar(
            select(SavedSelection)
            .where(
                SavedSelection.id == UUID(selection_id),
                SavedSelection.owner_sub == owner,
            )
            .with_for_update()
        )
        if row is None:
            raise PermissionError("Selection not available.")
        await session.delete(row)
        await session.commit()
