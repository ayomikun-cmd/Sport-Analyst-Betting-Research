import reflex as rx
import reflex_enterprise as rxe

import asyncio
import logging
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app import repositories
from app.research_service import (
    ChatView,
    MessageView,
    ResearchUnavailable,
    research,
    service_available,
)


class ResearchState(rx.State):
    chats: list[ChatView] = []
    messages: list[MessageView] = []
    active_chat: str = ""
    draft: str = ""
    submitted_prompt: str = ""
    pending_prompt: str = ""
    pending_message: str = ""
    busy: bool = False
    researching: bool = False
    cancel_requested: bool = False
    history_open: bool = False
    live_available: bool = False
    sample_mode: bool = True
    error: str = ""
    _worker_active: bool = False

    @rxe.event
    def toggle_history(self):
        self.history_open = not self.history_open

    @rxe.event
    def choose_prompt(self, prompt: str):
        if not self.busy:
            self.draft = prompt[:3000]

    @rxe.event
    def set_sample_mode(self, sample: bool):
        if not self.busy:
            self.sample_mode = sample or not self.live_available

    @rxe.event
    def new_research(self):
        if self.busy:
            return
        self.active_chat = ""
        self.messages = []
        self.draft = ""
        self.pending_prompt = ""
        self.pending_message = ""
        self.error = ""
        self.history_open = False

    @rxe.event
    def cancel_research(self):
        if self.researching:
            self.cancel_requested = True

    @rxe.event
    def submit(self, form_data: dict[str, Any]):
        if self.busy:
            return
        prompt = str(form_data.get("prompt", "")).strip()
        if not prompt or len(prompt) > 3000:
            self.error = (
                "Enter match details or a question, up to 3,000 characters."
            )
            self.draft = prompt[:3000]
            return
        self.draft = prompt
        self.submitted_prompt = prompt
        self.busy = True
        self.researching = True
        self.cancel_requested = False
        self.error = ""
        return ResearchState.run_research

    @rxe.event(background=True)
    async def load(self):
        async with self:
            if self.busy:
                return
            self.busy = True
        try:
            available = service_available()
            chats = await repositories.list_chats()
            async with self:
                self.live_available = available
                self.sample_mode = not available
                self.chats = chats
                self.error = ""
        except (SQLAlchemyError, PermissionError):
            async with self:
                self.error = "Saved research could not be loaded. Please refresh to retry."
        finally:
            async with self:
                self.busy = False

    @rxe.event(background=True)
    async def open_chat(self, chat_id: str):
        async with self:
            if self.busy:
                return
            self.busy = True
            self.error = ""
        try:
            messages = await repositories.load_messages(chat_id)
            async with self:
                self.active_chat = chat_id
                self.messages = messages
                self.history_open = False
                self.draft = ""
                self.pending_prompt = ""
                self.pending_message = ""
                if messages and messages[-1]["role"] == "user":
                    self.pending_prompt = messages[-1]["content"]
                    self.pending_message = messages[-1]["id"]
                    self.draft = self.pending_prompt
        except (SQLAlchemyError, PermissionError, ValueError):
            async with self:
                self.error = (
                    "This research could not be opened. Please try again."
                )
        finally:
            async with self:
                self.busy = False

    @rxe.event(background=True)
    async def run_research(self):
        task: asyncio.Task | None = None
        async with self:
            if not self.researching or self._worker_active:
                return
            self._worker_active = True
            prompt = self.submitted_prompt
            chat_id = self.active_chat
            sample = self.sample_mode
            reuse = bool(self.pending_message and self.pending_prompt == prompt)
        try:
            if not reuse:
                chat_id, message = await repositories.save_prompt(
                    chat_id, prompt, "sample" if sample else "live"
                )
                async with self:
                    self.active_chat = chat_id
                    self.messages.append(message)
                    self.pending_message = message["id"]
                    self.pending_prompt = prompt
            messages = await repositories.load_messages(chat_id)
            history = [
                {"role": item["role"], "content": item["content"]}
                for item in messages
                if item["role"] == "user"
                or (item["role"] == "assistant" and item["status"] != "sample")
            ]
            task = asyncio.create_task(research(history, sample=sample))
            while not task.done():
                await asyncio.wait({task}, timeout=0.25)
                async with self:
                    cancelled = self.cancel_requested
                if cancelled:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    async with self:
                        self.error = "Research cancelled. Your prompt is saved and ready to retry."
                    return
            result = await task
            async with self:
                cancelled = self.cancel_requested
            if cancelled:
                async with self:
                    self.error = "Research cancelled. Your prompt is saved and ready to retry."
                return
            reply = await repositories.save_reply(chat_id, result)
            async with self:
                self.messages.append(reply)
                self.draft = ""
                self.pending_message = ""
                self.pending_prompt = ""
            chats = await repositories.list_chats()
            async with self:
                self.chats = chats
        except ResearchUnavailable as error:
            async with self:
                self.error = str(error)
        except (SQLAlchemyError, PermissionError, ValueError):
            async with self:
                self.error = "Research could not be saved or loaded. Your input is retained; please retry."
        except Exception:
            logging.exception("Football research workflow failed")
            async with self:
                self.error = "Research could not be completed. Your input is retained; please retry."
        finally:
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            async with self:
                self.busy = False
                self.researching = False
                self.cancel_requested = False
                self._worker_active = False
            yield rx.call_script(
                "document.getElementById('thread-end')?.scrollIntoView({block:'end', behavior:'smooth'})"
            )
