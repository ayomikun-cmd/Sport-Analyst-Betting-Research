import reflex as rx
import reflex_enterprise as rxe

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from app import repositories
from app.models import SavedSelection
from app.odds_service import (
    BOOKMAKERS,
    FixtureView,
    QuoteView,
    SelectionView,
    OddsUnavailable,
    available,
    calculate,
    comparison_key,
    decimal_price,
    demo_quotes,
    fetch_quotes,
    freshness,
    search_fixtures,
    selection_view,
    timestamp,
    utc_input,
)
from app.research_service import ChatView, MessageView

DRAFT_DEFAULTS = {
    "home": "",
    "away": "",
    "competition": "",
    "kickoff": "",
    "market": "",
    "outcome": "",
    "line": "",
    "period": "match",
    "subject": "",
    "cards": "",
    "rules": "",
    "rationale": "",
    "bookmaker": "SportyBet",
    "price": "",
    "observed": "",
    "chat": "",
}


class SelectionsState(rx.State):
    selections: list[SelectionView] = []
    chats: list[ChatView] = []
    messages: list[MessageView] = []
    linked_chat: str = ""
    linked_title: str = ""
    fixtures: list[FixtureView] = []
    quotes: list[QuoteView] = []
    demo: bool = False
    feed_available: bool = False
    loading: bool = False
    fetching: bool = False
    saving: bool = False
    error: str = ""
    notice: str = ""
    search_notice: str = ""
    search_start: str = ""
    search_end: str = ""
    filter_text: str = ""
    chosen_quote: str = ""
    chosen_label: str = ""
    fixture_label: str = ""
    editing_id: str = ""
    draft: dict[str, str] = DRAFT_DEFAULTS.copy()
    bankroll: str = ""
    risk: str = "1"
    stake: str = ""
    calculator_context: str = ""
    calculator_error: str = ""
    result: dict[str, str] = {
        "maximum": "",
        "stake": "",
        "gross": "",
        "profit": "",
    }
    _quote_cache: list[QuoteView] = []
    _fixture_cache: list[FixtureView] = []
    _selected_fixture: dict[str, str] = {}
    _calc: dict[str, str] = {}
    _pending: dict[str, str] = {}
    _editing_status: str = "manual"

    @rxe.var(initial_value=[])
    def filtered_fixtures(self) -> list[FixtureView]:
        query = self.filter_text.casefold().strip()
        return [
            row
            for row in self.fixtures
            if not query
            or query
            in f"{row['home']} {row['away']} {row['competition']}".casefold()
        ]

    @rxe.var(initial_value=[])
    def bookmaker_coverage(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for book in BOOKMAKERS:
            offered = [
                quote for quote in self.quotes if quote["bookmaker"] == book
            ]
            if book == "BetKing":
                status = "Verified feed unavailable · manual entry only"
            elif self.demo:
                status = "Fictional sample prices · not verified coverage"
            elif not self.quotes:
                status = "Not checked · select an exact fixture"
            elif not offered:
                status = "No market returned for this fixture · not offered"
            elif not any(quote["eligible"] for quote in offered):
                status = "Prices unavailable, stale, or unverified"
            else:
                status = "Market-level observations · review settlement gaps"
            rows.append({"bookmaker": book, "status": status})
        return rows

    @rxe.event
    def filter_fixtures(self, value: str):
        self.filter_text = value[:100]

    @rxe.event
    def set_demo(self, demo: bool):
        if self.fetching or self.saving:
            return
        self.demo = demo
        self.quotes = demo_quotes() if demo else []
        self._quote_cache = demo_quotes() if demo else []
        self._selected_fixture = {}
        self.fixtures = []
        self._fixture_cache = []
        self.chosen_quote = ""
        self.chosen_label = ""
        self._calc = {}
        self.calculator_context = ""
        self.result = {"maximum": "", "stake": "", "gross": "", "profit": ""}
        self.fixture_label = (
            "Northbridge FC vs Riverside FC · fictional fixture" if demo else ""
        )
        self.error = ""
        self.search_notice = ""

    @rxe.event(background=True)
    async def load(self):
        async with self:
            if self.loading:
                return
            self.loading = True
            self.error = ""
            raw = self.router.url.query_parameters.get("chat", "")
            chat_id = raw if isinstance(raw, str) else ""
        try:
            chats = await repositories.list_chats()
            selections = [
                selection_view(row)
                for row in await repositories.list_saved_selections()
            ]
            async with self:
                self.chats = chats
                self.selections = selections
                self.feed_available = available()
                self.linked_chat = ""
                self.linked_title = ""
                self.messages = []
                self.draft["chat"] = ""
            messages = (
                await repositories.load_messages(chat_id) if chat_id else []
            )
            title = next(
                (chat["title"] for chat in chats if chat["id"] == chat_id), ""
            )
            async with self:
                self.linked_chat = chat_id
                self.linked_title = title
                self.messages = messages
                self.draft["chat"] = chat_id
        except (SQLAlchemyError, PermissionError, ValueError):
            async with self:
                self.error = "Saved selections or linked research could not be loaded. Only your own research can be linked; retry without the chat query."
                self.linked_chat = ""
                self.linked_title = ""
                self.messages = []
        finally:
            async with self:
                self.loading = False

    @rxe.event
    def link_research(self, form_data: dict[str, Any]):
        if not self.loading:
            self._pending = {"chat": str(form_data.get("chat", ""))}
            return SelectionsState.load_linked_research

    @rxe.event(background=True)
    async def load_linked_research(self):
        async with self:
            self.loading = True
            chat_id = self._pending.get("chat", "")
        try:
            messages = (
                await repositories.load_messages(chat_id) if chat_id else []
            )
            async with self:
                self.linked_chat = chat_id
                self.linked_title = next(
                    (
                        chat["title"]
                        for chat in self.chats
                        if chat["id"] == chat_id
                    ),
                    "",
                )
                self.messages = messages
                self.draft["chat"] = chat_id
                self.error = ""
        except (SQLAlchemyError, PermissionError, ValueError):
            async with self:
                self.error = "This research is unavailable or does not belong to your account."
        finally:
            async with self:
                self.loading = False

    @rxe.event
    def search(self, form_data: dict[str, Any]):
        if self.fetching or self.demo:
            return
        self.search_start = str(form_data.get("from", "")).strip()
        self.search_end = str(form_data.get("to", "")).strip()
        self.error = ""
        self.quotes = []
        self._quote_cache = []
        self.fixtures = []
        self._fixture_cache = []
        self.chosen_quote = ""
        self.chosen_label = ""
        self._calc = {}
        self.calculator_context = ""
        self.result = {"maximum": "", "stake": "", "gross": "", "profit": ""}
        self.search_notice = ""
        self.fixture_label = ""
        self._selected_fixture = {}
        if not available():
            self.fetching = False
            self.error = "Live odds credentials are missing. Connect the odds feed securely, use manual prices, or explicitly enable the fictional demo."
            return
        self.fetching = True
        return SelectionsState.run_search

    @rxe.event(background=True)
    async def run_search(self):
        async with self:
            start, end = self.search_start, self.search_end
        try:
            fixtures, note = await search_fixtures(start, end)
            async with self:
                self.fixtures = fixtures
                self._fixture_cache = fixtures
                self.search_notice = note
        except (OddsUnavailable, ValueError) as error:
            async with self:
                self.error = str(error)
        finally:
            async with self:
                self.fetching = False

    @rxe.event(background=True)
    async def choose_fixture(self, identity: str):
        async with self:
            if self.fetching or self.demo or self.saving:
                return
            fixture = next(
                (
                    dict(row)
                    for row in self._fixture_cache
                    if row["id"] == identity
                ),
                {},
            )
            if not fixture:
                self.error = (
                    "Select an exact fixture from your current search results."
                )
                return
            self.fetching = True
            self.error = ""
            self.quotes = []
            self._quote_cache = []
            self.chosen_quote = ""
            self.chosen_label = ""
            self._calc = {}
            self.calculator_context = ""
            self.result = {
                "maximum": "",
                "stake": "",
                "gross": "",
                "profit": "",
            }
        try:
            quotes = await fetch_quotes(fixture)
            async with self:
                self._selected_fixture = fixture
                self._quote_cache = quotes
                self.quotes = quotes
                self.fixture_label = f"{fixture['home']} vs {fixture['away']} · {fixture['competition']} · {fixture['kickoff']}"
                if not quotes:
                    self.notice = "No supported prices returned for this exact fixture. This is not a global availability claim; use manual entry or choose no bet."
        except (OddsUnavailable, ValueError) as error:
            async with self:
                self.error = str(error)
        finally:
            async with self:
                self.fetching = False

    @rxe.event
    def choose_quote(self, identity: str):
        if self.fetching or self.saving:
            return
        quote = next(
            (row for row in self._quote_cache if row["id"] == identity), None
        )
        if not quote or not quote["eligible"]:
            self.error = "This price is unavailable, stale, or unsupported. Refresh the feed or use a reviewed manual price."
            return
        self.chosen_quote = identity
        self.chosen_label = f"{quote['home']} vs {quote['away']} · {quote['bookmaker']} · {quote['market']} / {quote['outcome']} {quote['line']} · {quote['period']} · {quote['price']}"
        self._calc = {
            key: str(quote[key])
            for key in ("price", "observed", "kickoff", "status")
        }
        self.calculator_context = (
            f"{quote['status'].upper()} · {self.chosen_label}"
        )
        self.result = {"maximum": "", "stake": "", "gross": "", "profit": ""}
        self.calculator_error = ""

    @rxe.event
    def cancel_edit(self):
        if not self.saving:
            self.editing_id = ""
            self._editing_status = "manual"
            self.draft = {**DRAFT_DEFAULTS, "chat": self.linked_chat}

    @rxe.event(background=True)
    async def edit_selection(self, identity: str):
        async with self:
            if self.saving:
                return
            self.saving = True
        try:
            row = await repositories.get_saved_selection(identity)
            view = selection_view(row)
            async with self:
                self.draft = {key: view.get(key, "") for key in DRAFT_DEFAULTS}
                self.editing_id = identity
                self._editing_status = row.data_status
                self.notice = "Editing a feed selection converts its edited details to MANUAL unverified. Sample selections remain SAMPLE."
                self.error = ""
        except (SQLAlchemyError, PermissionError, ValueError):
            async with self:
                self.error = "Selection could not be opened. Please retry."
        finally:
            async with self:
                self.saving = False

    @rxe.event
    def save_manual(self, form_data: dict[str, Any]):
        if self.saving:
            return
        self.draft = {
            key: str(form_data.get(key, "")).strip()[:4000]
            for key in DRAFT_DEFAULTS
        }
        self.error = ""
        self.saving = True
        return SelectionsState.persist_manual

    def _manual_model(
        self, draft: dict[str, str], sample: bool
    ) -> SavedSelection:
        for key in (
            "home",
            "away",
            "competition",
            "kickoff",
            "market",
            "outcome",
            "period",
            "rationale",
        ):
            if not draft[key]:
                raise ValueError(
                    "Enter exact teams, competition, kickoff with timezone, market, outcome, period, and your personally reviewed rationale. No bet is a valid outcome."
                )
        if (
            draft["home"] == draft["away"]
            or draft["bookmaker"] not in BOOKMAKERS
        ):
            raise ValueError(
                "Choose different home and away teams and a supported bookmaker."
            )
        kickoff = timestamp(draft["kickoff"])
        price = decimal_price(draft["price"]) if draft["price"] else None
        observed = timestamp(draft["observed"]) if price else None
        if price and not sample:
            if kickoff <= datetime.now(timezone.utc):
                raise ValueError(
                    "Kickoff has passed. Do not use live or settled fixtures for pre-match prices; record no bet without odds instead."
                )
            if observed > datetime.now(timezone.utc):
                raise ValueError(
                    "A manual observation cannot be in the future."
                )
        line = None
        if draft["line"]:
            try:
                value = Decimal(draft["line"])
                if not value.is_finite():
                    raise ValueError(
                        "Line must be finite, or an exact split-line operator label."
                    )
                if (
                    abs(value) >= Decimal("1000000000000")
                    or value.as_tuple().exponent < -6
                ):
                    raise ValueError("Line is outside the supported precision.")
                line = value
            except InvalidOperation:
                pass
        return SavedSelection(
            research_chat_id=UUID(draft["chat"]) if draft["chat"] else None,
            event_name=f"{draft['home']} vs {draft['away']}",
            home_team=draft["home"],
            away_team=draft["away"],
            competition=draft["competition"],
            kickoff_at=kickoff,
            market_key=draft["market"],
            market_name=draft["market"],
            market_period=draft["period"],
            outcome_key=draft["outcome"],
            outcome_name=draft["outcome"],
            line=line,
            line_label=draft["line"] or None,
            subject_name=draft["subject"] or None,
            card_definition=draft["cards"] or None,
            settlement_rules=draft["rules"] or None,
            bookmaker=draft["bookmaker"],
            decimal_odds=price,
            observed_at=observed,
            data_status="sample" if sample else "manual",
            is_sample=sample,
            is_live=False,
            source_provider="Fictional demonstration"
            if sample
            else "User-entered manual observation",
            research_rationale=draft["rationale"],
            evidence_provenance={
                "method": "personally reviewed user entry; not feed verified",
                "settlement_gap": not bool(draft["rules"]),
                "sample": sample,
                "no_bet": not bool(price),
                "fixture_status": "user entered; not independently verified",
            },
        )

    @rxe.event(background=True)
    async def persist_manual(self):
        async with self:
            draft = dict(self.draft)
            identity = self.editing_id
            sample = self._editing_status == "sample" or (
                draft["home"] == "Northbridge FC"
                and draft["away"] == "Riverside FC"
            )
        try:
            model = self._manual_model(draft, sample)
            await repositories.save_selection(model, identity)
            selections = [
                selection_view(row)
                for row in await repositories.list_saved_selections()
            ]
            async with self:
                self.selections = selections
                self.editing_id = ""
                self._editing_status = "manual"
                self.draft = {**DRAFT_DEFAULTS, "chat": self.linked_chat}
                self.notice = (
                    "Sample selection saved."
                    if sample
                    else "Manual unverified selection saved. No bet was placed."
                )
        except ValueError as error:
            async with self:
                self.error = str(error)
        except (SQLAlchemyError, PermissionError):
            async with self:
                self.error = "Selection could not be saved. Your details are retained; verify the linked chat belongs to you and retry."
        finally:
            async with self:
                self.saving = False

    @rxe.event
    def save_quote(self, form_data: dict[str, Any]):
        if self.saving or self.fetching:
            return
        rationale = str(form_data.get("rationale", "")).strip()
        if not rationale or not form_data.get("reviewed"):
            self.error = "Add your cited rationale or explicit evidence gaps, and confirm personal review. Research is not an endorsement of a pick."
            return
        self._pending = {
            "rationale": rationale[:4000],
            "rules": str(form_data.get("rules", "")).strip()[:4000],
            "chat": str(form_data.get("chat", "")),
        }
        self.saving = True
        self.error = ""
        return SelectionsState.persist_quote

    @rxe.event(background=True)
    async def persist_quote(self):
        async with self:
            quote = next(
                (
                    dict(row)
                    for row in self._quote_cache
                    if row["id"] == self.chosen_quote
                ),
                {},
            )
            fixture = dict(self._selected_fixture)
            details = dict(self._pending)
        try:
            if not quote or not quote["eligible"]:
                raise ValueError("Select an eligible price first.")
            if len(details.get("rationale", "").strip()) == 0:
                raise ValueError(
                    "Add your personally reviewed rationale before saving."
                )
            if quote["status"] != "sample":
                refreshed = await fetch_quotes(fixture)
                matched = next(
                    (
                        row
                        for row in refreshed
                        if row["id"] == quote["id"]
                        and comparison_key(row) == comparison_key(quote)
                        and row["price"] == quote["price"]
                        and row["eligible"]
                    ),
                    None,
                )
                if not matched:
                    raise ValueError(
                        "The chosen price changed, became stale, or is no longer offered. Refresh odds and explicitly select a price again."
                    )
                quote = matched
            sample = quote["status"] == "sample"
            model = SavedSelection(
                research_chat_id=UUID(details["chat"])
                if details["chat"]
                else None,
                event_name=f"{quote['home']} vs {quote['away']}",
                home_team=quote["home"],
                away_team=quote["away"],
                competition=quote["competition"],
                kickoff_at=timestamp(quote["kickoff"]),
                canonical_event_id=quote["event_id"],
                market_key=quote["market"],
                market_name=quote["market"],
                market_period=quote["period"],
                outcome_key=quote["outcome"],
                outcome_name=quote["outcome"],
                line_label=quote["line"] or None,
                subject_name=quote["subject"] or None,
                card_definition=quote["cards"] or None,
                settlement_rules=quote["rules"] or None,
                bookmaker=quote["bookmaker"],
                decimal_odds=decimal_price(quote["price"]),
                observed_at=timestamp(quote["observed"]),
                data_status="sample" if sample else "verified",
                is_sample=sample,
                is_live=False,
                source_provider=quote["source"],
                source_url="" if sample else "https://api.odds-api.io",
                source_event_id=quote["event_id"],
                source_market_id=quote["market"],
                source_outcome_id=quote["outcome"],
                bookmaker_event_url=quote["url"] or None,
                research_rationale=details["rationale"],
                evidence_provenance={
                    "method": "fixed fictional sample"
                    if sample
                    else "server refetched exact provider quote",
                    "raw_labels": quote["raw"],
                    "observed_at": quote["observed"],
                    "settlement_gap": not bool(quote["rules"]),
                    "user_settlement_notes": details["rules"],
                    "research_is_not_endorsement": True,
                },
            )
            await repositories.save_selection(model)
            selections = [
                selection_view(row)
                for row in await repositories.list_saved_selections()
            ]
            async with self:
                self.selections = selections
                self.notice = f"{model.data_status.upper()} selection saved. No bet was placed."
        except (ValueError, OddsUnavailable) as error:
            async with self:
                self.error = str(error)
        except (SQLAlchemyError, PermissionError):
            async with self:
                self.error = "The selection could not be saved. Check your linked research and retry; your inputs are retained."
        finally:
            async with self:
                self.saving = False

    @rxe.event(background=True)
    async def remove_selection(self, identity: str):
        async with self:
            if self.saving:
                return
            self.saving = True
        try:
            await repositories.delete_saved_selection(identity)
            selections = [
                selection_view(row)
                for row in await repositories.list_saved_selections()
            ]
            async with self:
                self.selections = selections
                self.notice = "Selection removed."
                self._calc = {}
                self.calculator_context = ""
                self.result = {
                    "maximum": "",
                    "stake": "",
                    "gross": "",
                    "profit": "",
                }
                if self.editing_id == identity:
                    self.editing_id = ""
                    self.draft = {**DRAFT_DEFAULTS, "chat": self.linked_chat}
        except (SQLAlchemyError, PermissionError, ValueError):
            async with self:
                self.error = "Selection could not be removed. Please retry."
        finally:
            async with self:
                self.saving = False

    @rxe.event(background=True)
    async def use_saved(self, identity: str):
        try:
            view = selection_view(
                await repositories.get_saved_selection(identity)
            )
            async with self:
                if not view["eligible"]:
                    self.calculator_error = "Odds are missing/stale or kickoff has passed. Edit with a current reviewed manual observation, refresh the feed, or choose no bet."
                    return
                self._calc = {
                    key: view[key]
                    for key in ("price", "observed", "kickoff", "status")
                }
                self.calculator_context = f"{view['status'].upper()} · {view['home']} vs {view['away']} · {view['bookmaker']} · {view['market']} / {view['outcome']} {view['line']} · {view['price']}"
                self.result = {
                    "maximum": "",
                    "stake": "",
                    "gross": "",
                    "profit": "",
                }
                self.calculator_error = ""
        except (SQLAlchemyError, PermissionError, ValueError):
            async with self:
                self.calculator_error = (
                    "This saved selection could not be loaded."
                )

    @rxe.event
    def calculate_return(self, form_data: dict[str, Any]):
        self.bankroll = str(form_data.get("bankroll", "")).strip()
        self.risk = str(form_data.get("risk", "1")).strip()
        self.stake = str(form_data.get("stake", "")).strip()
        self.result = {"maximum": "", "stake": "", "gross": "", "profit": ""}
        self.calculator_error = ""
        try:
            if not self._calc.get("price"):
                raise ValueError(
                    "Choose one comparison price or a saved selection with available odds. No fictitious return is shown for unavailable odds or no bet."
                )
            if self._calc["status"] != "sample":
                _, fresh = freshness(self._calc["observed"])
                if not fresh or timestamp(
                    self._calc["kickoff"]
                ) <= datetime.now(timezone.utc):
                    raise ValueError(
                        "This observation is stale or kickoff has passed. Refresh or edit the price before calculating."
                    )
            self.result = calculate(
                self.bankroll, self.risk, self.stake, self._calc["price"]
            )
        except ValueError as error:
            self.calculator_error = str(error)
