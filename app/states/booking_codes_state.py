import reflex as rx
import reflex_enterprise as rxe

from datetime import datetime, timezone
from decimal import Decimal, localcontext
from typing import Any, TypedDict
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError

from app import repositories
from app.odds_service import (
    BOOKMAKERS,
    SelectionView,
    decimal_price,
    freshness,
    selection_view,
    timestamp,
)

OFFICIAL_SITES = {
    "SportyBet": "https://www.sportybet.com/ng",
    "Bet9ja": "https://www.bet9ja.com",
    "BetKing": "https://www.betking.com.ng",
}
UNSUPPORTED = "Code cannot be resolved or converted: no verified operator integration. Load the slip in its source bookmaker and enter/import the selections below."
FIELDS = {
    "home": "",
    "away": "",
    "competition": "",
    "category": "",
    "kickoff": "",
    "market": "",
    "outcome": "",
    "line": "",
    "period": "",
    "subject": "",
    "cards": "",
    "rules": "",
    "bookmaker": "SportyBet",
    "price": "",
    "observed": "",
    "destination_price": "",
    "destination_observed": "",
    "evidence": "",
    "rationale": "",
}
IDENTITY_FIELDS = (
    "home",
    "away",
    "competition",
    "category",
    "kickoff",
    "market",
    "outcome",
    "line",
    "period",
    "subject",
    "cards",
    "rules",
)


class TransferLeg(TypedDict):
    id: str
    saved_id: str
    chat: str
    details: dict[str, str]
    original: dict[str, str]
    provenance: str
    source_status: str
    live: bool
    included: bool
    event_reviewed: bool
    market_reviewed: bool
    missing: bool
    changed: bool
    manual_edits: bool
    reason: str
    status: str
    gaps: str


class BookingCodesState(rx.State):
    source: str = "SportyBet"
    destination: str = "Bet9ja"
    code: str = ""
    conversion_notice: str = ""
    selections: list[SelectionView] = []
    legs: list[TransferLeg] = []
    draft: dict[str, str] = FIELDS.copy()
    editing_id: str = ""
    form_version: int = 0
    loading: bool = False
    error: str = ""
    notice: str = ""
    output: str = ""
    total_odds: str = ""
    _revision: int = 0

    def _invalidate(self):
        self.output = ""
        self.total_odds = ""
        self.notice = ""
        self.error = ""
        self._revision += 1

    def _gaps(self, leg: TransferLeg) -> list[str]:
        d = leg["details"]
        gaps: list[str] = []
        if leg["source_status"] == "sample":
            gaps.append(
                "SAMPLE / fictional — not transferable to a real bookmaker"
            )
        try:
            if leg["live"] or timestamp(d["kickoff"]) <= datetime.now(
                timezone.utc
            ):
                gaps.append(
                    "Started / in-play / settled — explicitly exclude from prematch transfer"
                )
        except ValueError:
            gaps.append("Unknown kickoff — clarify exact UTC date/time")
        for key in (
            "home",
            "away",
            "competition",
            "category",
            "market",
            "outcome",
            "period",
            "rules",
            "evidence",
        ):
            if not d[key] or d[key].casefold() in {
                "unknown",
                "settlement definition unknown",
                "n/a",
            }:
                gaps.append(f"Review required: {key}")
        if any(
            word in d["market"].casefold() for word in ("card", "booking")
        ) and (not d["cards"] or "unknown" in d["cards"].casefold()):
            gaps.append(
                "Card settlement definition missing: cards/points, reds, second yellows, bench"
            )
        if leg["missing"]:
            gaps.append(
                "Destination market missing — exclude or explicitly edit as a NEW changed selection"
            )
        if not leg["event_reviewed"]:
            gaps.append("Exact destination event not personally confirmed")
        if not leg["market_reviewed"]:
            gaps.append(
                "Exact market, line, outcome, period, subject and settlement not personally confirmed"
            )
        return gaps

    def _decorate(self, leg: TransferLeg) -> TransferLeg:
        gaps = self._gaps(leg)
        if any(gap.startswith("Started") for gap in gaps):
            status = (
                "Started / settled — blocked"
                if leg["included"]
                else "Excluded · started / settled"
            )
        elif not leg["included"]:
            status = "Excluded · reversible"
        elif leg["source_status"] == "sample":
            status = "SAMPLE · not real transfer"
        elif leg["missing"]:
            status = "Missing destination market"
        elif not gaps:
            status = "Manually confirmed · NOT automatically matched"
        else:
            status = "Unreviewed / unresolved"
        return {**leg, "status": status, "gaps": "; ".join(gaps)}

    @rxe.var(initial_value=[])
    def reviewed_legs(self) -> list[TransferLeg]:
        return [self._decorate(leg) for leg in self.legs]

    @rxe.var(
        initial_value={
            "included": 0,
            "confirmed": 0,
            "excluded": 0,
            "unresolved": 0,
        }
    )
    def counts(self) -> dict[str, int]:
        included = [leg for leg in self.legs if leg["included"]]
        confirmed = sum(not self._gaps(leg) for leg in included)
        return {
            "included": len(included),
            "confirmed": confirmed,
            "excluded": len(self.legs) - len(included),
            "unresolved": len(included) - confirmed,
        }

    @rxe.var(initial_value="https://www.bet9ja.com")
    def destination_site(self) -> str:
        return OFFICIAL_SITES.get(self.destination, "https://www.bet9ja.com")

    @rxe.event
    def set_bookmaker(self, side: str, value: str):
        if side not in {"source", "destination"} or value not in BOOKMAKERS:
            self.error = "Choose SportyBet, Bet9ja or BetKing explicitly. Source is never guessed from a code."
            return
        if getattr(self, side) == value:
            return
        setattr(self, side, value)
        self._invalidate()
        self.conversion_notice = ""
        self.legs = [
            {
                **leg,
                "event_reviewed": False,
                "market_reviewed": False,
                "missing": False,
                "details": {
                    **leg["details"],
                    "destination_price": "",
                    "destination_observed": "",
                    "evidence": "",
                },
            }
            for leg in self.legs
        ]
        self.draft["destination_price"] = ""
        self.draft["destination_observed"] = ""
        self.draft["evidence"] = ""
        self.form_version += 1
        self.notice = "Bookmaker changed. Destination prices and confirmations reset; original leg source details remain unchanged."

    @rxe.event
    def set_code(self, value: str):
        self._invalidate()
        self.code = value[:257]
        self.conversion_notice = ""

    @rxe.event
    def check_conversion(self):
        self._invalidate()
        if not self.code.strip():
            self.error = "Enter an existing source booking code (maximum 256 characters). Source must be selected explicitly."
        elif len(self.code) > 256 or any(ord(c) < 32 for c in self.code):
            self.error = "Code must be at most 256 characters without control characters."
        else:
            self.conversion_notice = UNSUPPORTED

    @rxe.event
    def native_code(self):
        self.conversion_notice = "Native booking-code generation unavailable: no verified operator creator integration for SportyBet, Bet9ja or BetKing. Prepare a manual transfer checklist instead; it is NOT a bookmaker code."

    @rxe.event(background=True)
    async def load(self):
        async with self:
            if self.loading:
                return
            self.loading = True
            self._invalidate()
            self.legs = []
            self.selections = []
            self.editing_id = ""
            self.draft = {**FIELDS, "bookmaker": self.source}
            self.form_version += 1
            raw = self.router.url.query_parameters.get("selection", "")
            identity = raw if isinstance(raw, str) and len(raw) <= 36 else ""
            invalid = bool(raw) and not identity
        try:
            selections = [
                selection_view(row)
                for row in await repositories.list_saved_selections()
            ]
            async with self:
                self.selections = selections
                if invalid:
                    self.error = "Invalid selection link. Import one of your own saved selections below."
        except (SQLAlchemyError, PermissionError, ValueError):
            async with self:
                self.error = "Your private saved selections could not be loaded. Retry loading saved selections; manual entry remains available."
        finally:
            async with self:
                self.loading = False
        if identity:
            yield BookingCodesState.import_saved(identity)

    @rxe.event(background=True)
    async def refresh_saved(self):
        async with self:
            if self.loading:
                return
            self.loading = True
        try:
            selections = [
                selection_view(row)
                for row in await repositories.list_saved_selections()
            ]
            async with self:
                self.selections = selections
                self.error = ""
                self.notice = (
                    "Private saved selections refreshed. Draft unchanged."
                )
        except (SQLAlchemyError, PermissionError, ValueError):
            async with self:
                self.error = "Private saved selections unavailable. Retry; the transfer draft is retained."
        finally:
            async with self:
                self.loading = False

    def _equivalent(self, a: dict[str, str], b: dict[str, str]) -> bool:
        return all(
            a[key].strip().casefold() == b[key].strip().casefold()
            for key in IDENTITY_FIELDS
        )

    def _insert(self, leg: TransferLeg):
        if len(self.legs) >= 50:
            raise ValueError(
                "A transfer draft supports at most 50 legs. Remove a leg before adding another."
            )
        if any(
            (leg["saved_id"] and row["saved_id"] == leg["saved_id"])
            or self._equivalent(row["details"], leg["details"])
            for row in self.legs
        ):
            raise ValueError(
                "This saved ID or equivalent exact leg is already in the draft."
            )
        self._invalidate()
        self.legs = [*self.legs, leg]

    @rxe.event(background=True)
    async def import_saved(self, identity: str):
        async with self:
            if self.loading:
                return
            self.loading = True
            revision = self._revision
        try:
            UUID(identity)
            row = await repositories.get_saved_selection(identity)
            view = selection_view(row)
            messages = (
                await repositories.load_messages(view["chat"])
                if view["chat"]
                else []
            )
            sources = []
            for message in messages:
                for source in message["sources"]:
                    sources.append(str(source))
            details = {key: str(view.get(key, "")) for key in FIELDS}
            details["category"] = ""
            details["evidence"] = ""
            leg: TransferLeg = {
                "id": str(uuid4()),
                "saved_id": identity,
                "chat": view["chat"],
                "details": details,
                "original": dict(details),
                "provenance": f"Saved selection {identity} · {view['source']} · Source URL (text only): {view['url']}\nResearch source records: {'; '.join(sources) or 'No linked source records; evidence remains a gap.'}",
                "source_status": "sample" if row.is_sample else view["status"],
                "live": bool(row.is_live)
                or str(
                    (row.evidence_provenance or {}).get("fixture_status", "")
                ).casefold()
                in {
                    "started",
                    "settled",
                    "finished",
                    "live",
                    "inplay",
                    "in-play",
                },
                "included": True,
                "event_reviewed": False,
                "market_reviewed": False,
                "missing": False,
                "changed": False,
                "manual_edits": False,
                "reason": "",
                "status": "",
                "gaps": "",
            }
            async with self:
                if revision != self._revision:
                    self.error = "Draft changed during import. Import again to review against the current destination."
                    return
                self._insert(leg)
                self.notice = "Owned saved selection imported with original source and rationale. Clarify category and personally review the exact destination event/settlement."
        except ValueError as error:
            async with self:
                self.error = (
                    str(error)
                    if str(error).startswith(("A transfer", "This saved"))
                    else "Invalid selection ID. Choose your own saved selection."
                )
        except (SQLAlchemyError, PermissionError):
            async with self:
                self.error = "Selection or linked research unavailable or not owned by your account. No leg was imported."
        finally:
            async with self:
                self.loading = False

    @rxe.event
    def edit_leg(self, identity: str):
        leg = next((row for row in self.legs if row["id"] == identity), None)
        if leg:
            self._invalidate()
            self.editing_id = identity
            self.draft = dict(leg["details"])
            self.form_version += 1

    @rxe.event
    def revert_leg(self, identity: str):
        self._invalidate()
        self.legs = [
            {
                **leg,
                "details": {
                    **leg["original"],
                    "destination_price": "",
                    "destination_observed": "",
                    "evidence": "",
                },
                "changed": False,
                "manual_edits": False,
                "event_reviewed": False,
                "market_reviewed": False,
                "missing": False,
            }
            if leg["id"] == identity
            else leg
            for leg in self.legs
        ]
        if self.editing_id == identity:
            self.cancel_edit()
        self.notice = "Original source details restored. Destination observations and review reset. Inclusion/exclusion remains your explicit choice."

    @rxe.event
    def cancel_edit(self):
        self.editing_id = ""
        self.draft = {**FIELDS, "bookmaker": self.source}
        self.form_version += 1

    def _validate_details(self, form_data: dict[str, Any]) -> dict[str, str]:
        d: dict[str, str] = {}
        for key in FIELDS:
            value = str(form_data.get(key, "")).strip()
            limit = (
                4000
                if key in {"rationale", "evidence", "rules", "cards"}
                else 200
            )
            if len(value) > limit or any(
                ord(c) < 32 and c not in "\n\t\r" for c in value
            ):
                raise ValueError(
                    f"{key}: maximum {limit} characters; no control characters."
                )
            d[key] = value
        for key in (
            "home",
            "away",
            "competition",
            "market",
            "outcome",
            "period",
        ):
            if not d[key]:
                raise ValueError(
                    "Enter exact home/away teams, competition, market, outcome and period."
                )
        if (
            d["home"].casefold() == d["away"].casefold()
            or d["bookmaker"] not in BOOKMAKERS
        ):
            raise ValueError(
                "Choose different teams and a supported source bookmaker."
            )
        if d["kickoff"]:
            d["kickoff"] = timestamp(d["kickoff"]).isoformat()
        for price, observed in (
            ("price", "observed"),
            ("destination_price", "destination_observed"),
        ):
            if d[price]:
                value = decimal_price(d[price])
                d[price] = f"{value:.6f}".rstrip("0").rstrip(".")
                if not d[observed]:
                    raise ValueError(
                        "A price needs its explicit UTC observation timestamp."
                    )
            if d[observed]:
                at = timestamp(d[observed])
                if at > datetime.now(timezone.utc):
                    raise ValueError(
                        "Price observation cannot be in the future."
                    )
                d[observed] = at.isoformat()
        return d

    @rxe.event
    def save_leg(self, form_data: dict[str, Any]):
        self._invalidate()
        try:
            details = self._validate_details(form_data)
            if self.editing_id:
                leg = next(
                    (row for row in self.legs if row["id"] == self.editing_id),
                    None,
                )
                if not leg:
                    raise ValueError("This draft leg no longer exists.")
                if any(
                    row["id"] != leg["id"]
                    and self._equivalent(row["details"], details)
                    for row in self.legs
                ):
                    raise ValueError("An equivalent exact leg already exists.")
                changed = leg["changed"] or any(
                    details[key] != leg["details"][key]
                    for key in IDENTITY_FIELDS
                    if key != "category" or leg["details"]["category"]
                )
                if details["bookmaker"] != leg["details"]["bookmaker"]:
                    details = {
                        **details,
                        "destination_price": "",
                        "destination_observed": "",
                        "evidence": "",
                    }
                updated = {
                    **leg,
                    "details": details,
                    "changed": changed,
                    "manual_edits": True,
                    "event_reviewed": False,
                    "market_reviewed": False,
                    "missing": False,
                }
                self.legs = [
                    updated if row["id"] == leg["id"] else row
                    for row in self.legs
                ]
            else:
                self._insert(
                    {
                        "id": str(uuid4()),
                        "saved_id": "",
                        "chat": "",
                        "details": details,
                        "original": dict(details),
                        "provenance": "Personal manual entry — not independently verified",
                        "source_status": "manual",
                        "live": False,
                        "included": True,
                        "event_reviewed": False,
                        "market_reviewed": False,
                        "missing": False,
                        "changed": False,
                        "manual_edits": True,
                        "reason": "",
                        "status": "",
                        "gaps": "",
                    }
                )
            self.cancel_edit()
            self.notice = "Draft leg updated. Destination review reset. Changed event/market details are a NEW changed selection, never an equivalent substitution. No saved research was modified."
        except ValueError as error:
            self.error = str(error)

    @rxe.event
    def review_leg(self, identity: str, form_data: dict[str, Any]):
        self._invalidate()
        leg = next((row for row in self.legs if row["id"] == identity), None)
        if not leg:
            self.error = "Draft leg unavailable."
            return
        reviewed = {
            **leg,
            "event_reviewed": form_data.get("event") in (True, "on", "true"),
            "market_reviewed": form_data.get("market") in (True, "on", "true"),
        }
        gaps = self._gaps(reviewed)
        if gaps or not leg["included"]:
            self.error = (
                "; ".join(gaps) or "Reinclude this leg before confirmation."
            )
            return
        self.legs = [
            reviewed if row["id"] == identity else row for row in self.legs
        ]
        self.notice = "Personally confirmed exact destination details — manual review, not automatic matching. Destination odds remain manual/unverified."

    @rxe.event
    def mark_missing(self, identity: str):
        self._invalidate()
        self.legs = [
            {
                **leg,
                "missing": True,
                "event_reviewed": False,
                "market_reviewed": False,
                "reason": "Destination market missing; no automatic alternative",
            }
            if leg["id"] == identity
            else leg
            for leg in self.legs
        ]

    @rxe.event
    def set_inclusion(self, identity: str, form_data: dict[str, Any]):
        self._invalidate()
        for leg in self.legs:
            if leg["id"] == identity:
                reason = str(form_data.get("reason", "")).strip()
                if leg["included"] and (not reason or len(reason) > 500):
                    self.error = "Provide an exclusion reason (1–500 characters). Started or missing legs are never silently dropped."
                    return
                leg["included"] = not leg["included"]
                leg["reason"] = reason if not leg["included"] else ""
                leg["event_reviewed"] = False
                leg["market_reviewed"] = False
        self.legs = list(self.legs)

    @rxe.event
    def remove_leg(self, identity: str):
        self._invalidate()
        self.legs = [leg for leg in self.legs if leg["id"] != identity]
        if self.editing_id == identity:
            self.cancel_edit()

    def _build_output(self) -> tuple[str, str]:
        included = [leg for leg in self.legs if leg["included"]]
        if not included:
            raise ValueError(
                "Add and include at least one leg before preparing a manual checklist."
            )
        if any(leg["source_status"] == "sample" for leg in self.legs):
            raise ValueError(
                "SAMPLE legs cannot form a real bookmaker transfer. Remove fictional legs; do not mix sample and real selections."
            )
        for leg in included:
            gaps = self._gaps(leg)
            if leg["missing"] or any(
                gap.startswith(("Started", "Unknown kickoff")) for gap in gaps
            ):
                raise ValueError(
                    "Clarify unknown kickoff or explicitly exclude started/settled and missing-market legs before preparing. No leg is silently dropped."
                )
        correlated = len(
            {
                tuple(
                    leg["details"][key].strip().casefold()
                    for key in ("home", "away", "competition", "kickoff")
                )
                for leg in included
            }
        ) < len(included)
        total = Decimal(1)
        valid = not correlated and all(not self._gaps(leg) for leg in included)
        with localcontext() as ctx:
            ctx.prec = 40
            for leg in included:
                d = leg["details"]
                try:
                    price = decimal_price(d["destination_price"])
                    _, fresh = freshness(d["destination_observed"])
                    if not fresh:
                        valid = False
                    total *= price
                    if total >= Decimal("1000000000000"):
                        valid = False
                        break
                except ValueError:
                    valid = False
        odds = f"{total:.6f}".rstrip("0").rstrip(".") if valid else ""
        confirmed = sum(not self._gaps(leg) for leg in included)
        text = [
            "Manual transfer — NOT a bookmaker booking code",
            f"Source slip bookmaker (explicit, not detected): {self.source}",
            f"Destination: {self.destination}",
            "Individual original source bookmakers are retained below.",
            f"Included: {len(included)} | Manually confirmed: {confirmed} | Excluded: {len(self.legs) - len(included)} | Unresolved: {len(included) - confirmed}",
            f"Combined accumulator decimal odds: {odds or 'Unavailable — requires all included reviews and current valid destination manual prices; no correlated same-event legs; safety bound < 1 trillion.'}",
            "Destination prices: MANUAL / UNVERIFIED, never feed-matched. Current means observed within 10 minutes; recheck in the operator UI.",
        ]
        if correlated:
            text.append(
                "CAUTION: Same-event legs may be correlated or disallowed together. No independent multiplication/combined return claim."
            )
        for index, leg in enumerate(self.legs, 1):
            d = leg["details"]
            text.extend(
                [
                    "",
                    f"{index}. {'INCLUDED' if leg['included'] else 'EXCLUDED'} · {d['home']} vs {d['away']}",
                    f"Status: {self._decorate(leg)['status']} · Source data: {leg['source_status'].upper()} · {'NEW CHANGED selection / manual edits; NOT an equivalent replacement' if leg['changed'] else 'Original selection / manual destination review'}",
                    f"Exclusion reason: {leg['reason'] or 'None'}",
                ]
            )
            text.append(
                f"Current edited details: {'MANUAL / UNVERIFIED' if leg['manual_edits'] or leg['source_status'] == 'manual' else 'Original source details retained; destination always manual/unverified'}"
            )
            for key in FIELDS:
                text.append(
                    f"{key}: {d[key] or 'Unknown / not supplied (subject or line may be not applicable; personally verify)'}"
                )
            _, age_valid = freshness(d["destination_observed"])
            text.append(
                f"Destination price freshness: {'within 10 minutes' if age_valid else 'unknown / stale'} — manual/unverified"
            )
            research_link = (
                f"/selections?chat={leg['chat']}" if leg["chat"] else "None"
            )
            text.extend(
                [
                    f"Gaps: {'; '.join(self._gaps(leg)) or 'No recorded detail gaps; personal review only, not operator verification'}",
                    f"Original source details: {leg['original']}",
                    f"Provenance / rationale sources: {leg['provenance']}",
                    f"Linked research: {research_link}",
                ]
            )
        text.extend(
            [
                "",
                "No bets placed. Add/check every included selection in the destination bookmaker UI yourself; verify exact category, event, kickoff, line, period, outcome, subject and settlement. Unknown prices are not zero.",
                "Extra legs increase risk; no probabilities or guarantees are inferred. Use /selections for single-selection stake limits. 18+; only risk money you can afford to lose.",
            ]
        )
        return "\n".join(text), odds

    @rxe.event
    def prepare_manual_transfer(self):
        self._invalidate()
        try:
            self.output, self.total_odds = self._build_output()
            self.notice = "Manual checklist prepared, NOT a native booking code. Any unresolved legs remain explicit gaps, not ready-to-bet matches."
        except ValueError as error:
            self.error = str(error)

    def _export_current(self) -> bool:
        if not self.output:
            self.error = "Prepare a fresh manual checklist first."
            return False
        try:
            text, odds = self._build_output()
            if text != self.output or odds != self.total_odds:
                self._invalidate()
                self.error = "Kickoff, price freshness or review changed. Prepare the checklist again before copying/downloading."
                return False
        except ValueError as error:
            self._invalidate()
            self.error = str(error)
            return False
        return True

    @rxe.event
    def copy_checklist(self):
        if self._export_current():
            return rx.set_clipboard(self.output)

    @rxe.event
    def download_checklist(self):
        if self._export_current():
            return rx.download(
                data=self.output, filename="sport-analyst-manual-transfer.txt"
            )
