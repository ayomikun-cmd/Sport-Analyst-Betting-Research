import reflex as rx

from app.components.navigation import navigation
from app.odds_service import BOOKMAKERS, SelectionView
from app.states.booking_codes_state import (
    BookingCodesState,
    OFFICIAL_SITES,
    TransferLeg,
)

BUTTON = "inline-flex items-center justify-center gap-2 rounded-lg border border-white/15 bg-[#141416] px-3 py-2 text-xs font-medium text-[#F4F4F5] hover:border-white/30 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-[#EF233C]"
PRIMARY = "inline-flex items-center justify-center gap-2 rounded-lg bg-[#EF233C] px-4 py-2.5 text-xs font-semibold text-white hover:bg-[#D91F36] disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#EF233C]"
INPUT = "w-full min-w-0 rounded-lg border border-white/15 bg-[#09090B] px-3 py-2.5 text-xs text-[#F4F4F5] placeholder:text-zinc-500 focus:border-[#EF233C] focus:outline-hidden"
CARD = "rounded-xl border border-white/10 bg-[#141416] p-4 sm:p-5"
CORE_FIELDS = [
    {
        "key": "home",
        "label": "Exact home team",
        "hint": "Include women / U21 labels",
    },
    {
        "key": "away",
        "label": "Exact away team",
        "hint": "Exact operator team name",
    },
    {"key": "competition", "label": "Competition", "hint": "Exact competition"},
    {
        "key": "category",
        "label": "Category (mandatory review)",
        "hint": "Senior men / women / U21…",
    },
    {
        "key": "kickoff",
        "label": "Kickoff (explicit UTC)",
        "hint": "2026-08-01T15:00:00Z; blank stays unresolved",
    },
    {"key": "market", "label": "Exact market", "hint": "Operator market label"},
    {
        "key": "outcome",
        "label": "Exact outcome",
        "hint": "Exact pick, not an approximation",
    },
    {
        "key": "line",
        "label": "Exact line (if applicable)",
        "hint": "2.5 / split line; blank only if not applicable",
    },
    {"key": "period", "label": "Period", "hint": "90 minutes / first half…"},
    {
        "key": "subject",
        "label": "Subject (optional)",
        "hint": "Exact player / team where applicable",
    },
    {
        "key": "price",
        "label": "Source decimal odds (optional)",
        "hint": "Greater than 1; never inferred",
    },
    {
        "key": "observed",
        "label": "Source odds observed (UTC)",
        "hint": "2026-08-01T12:00:00Z",
    },
    {
        "key": "destination_price",
        "label": "Destination odds · manual/unverified",
        "hint": "Optional, greater than 1",
    },
    {
        "key": "destination_observed",
        "label": "Destination odds observed (UTC)",
        "hint": "Explicit current timestamp with Z",
    },
]
NOTE_FIELDS = [
    {
        "key": "cards",
        "label": "Card / booking-point definition",
        "hint": "Cards vs points; second yellows, reds, bench; not applicable for non-card markets",
    },
    {
        "key": "rules",
        "label": "Personally reviewed settlement rules",
        "hint": "90 min / extra time / voids; missing or unknown rules remain gaps",
    },
    {
        "key": "evidence",
        "label": "Destination personal evidence / review notes",
        "hint": "Describe what you checked in the destination UI, including exact event and settlement",
    },
    {
        "key": "rationale",
        "label": "Research rationale / sources / evidence gaps",
        "hint": "Original rationale retained on import; editing does not update saved research",
    },
]


def bookmaker_choice(
    side: str, label: str, current: rx.Var[str]
) -> rx.Component:
    return rx.el.div(
        rx.el.label(
            label,
            html_for=f"booking-{side}",
            class_name="mb-1.5 block text-xs text-zinc-300",
        ),
        rx.el.div(
            rx.el.select(
                rx.foreach(
                    BOOKMAKERS, lambda book: rx.el.option(book, value=book)
                ),
                id=f"booking-{side}",
                default_value=current,
                key=current,
                on_change=lambda value: BookingCodesState.set_bookmaker(
                    side, value
                ),
                class_name="w-full appearance-none rounded-lg border border-white/15 bg-[#09090B] py-2.5 pl-3 pr-8 text-xs text-[#F4F4F5] focus:border-[#EF233C] focus:outline-hidden",
            ),
            rx.icon(
                "chevron-down",
                class_name="pointer-events-none absolute right-3 top-3 h-4 w-4 text-zinc-400",
            ),
            class_name="relative",
        ),
    )


def conversion_controls() -> rx.Component:
    return rx.el.section(
        rx.el.div(
            bookmaker_choice(
                "source",
                "Source slip bookmaker · select explicitly",
                BookingCodesState.source,
            ),
            bookmaker_choice(
                "destination",
                "Destination bookmaker",
                BookingCodesState.destination,
            ),
            rx.el.div(
                rx.el.label(
                    "Existing source booking code",
                    html_for="booking-code",
                    class_name="mb-1.5 block text-xs text-zinc-300",
                ),
                rx.el.input(
                    id="booking-code",
                    default_value=BookingCodesState.code,
                    on_change=BookingCodesState.set_code.debounce(300),
                    max_length=257,
                    placeholder="No automatic source detection",
                    class_name=INPUT,
                ),
            ),
            rx.el.button(
                "Check conversion",
                on_click=BookingCodesState.check_conversion,
                class_name=BUTTON,
            ),
            class_name="grid items-end gap-3 sm:grid-cols-2 xl:grid-cols-[1fr_1fr_1.4fr_auto]",
        ),
        rx.el.p(
            "No native resolver, creator or converter is available without verified operator access. No selections are parsed from your code. Use the source bookmaker to open the slip, then import saved research or enter its legs below.",
            class_name="mt-3 text-xs leading-5 text-zinc-400",
        ),
        rx.cond(
            BookingCodesState.conversion_notice != "",
            rx.el.p(
                BookingCodesState.conversion_notice,
                role="status",
                class_name="mt-3 rounded-lg border border-[#EF233C]/30 bg-[#09090B] p-3 text-xs leading-5 text-[#F4F4F5]",
            ),
        ),
        aria_label="Source and destination",
        class_name=CARD,
    )


def saved_choice(selection: SelectionView) -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.p(
                f"{selection['home']} vs {selection['away']}",
                class_name="text-xs font-medium text-[#F4F4F5]",
            ),
            rx.el.p(
                f"{selection['status'].upper()} · {selection['bookmaker']} · {selection['market']} / {selection['outcome']} {selection['line']} · {selection['kickoff']}",
                class_name="mt-1 text-[11px] leading-5 text-zinc-400",
            ),
            class_name="min-w-0 flex-1",
        ),
        rx.el.button(
            rx.icon("plus", class_name="h-3.5 w-3.5"),
            "Add leg",
            on_click=BookingCodesState.import_saved(selection["id"]),
            disabled=BookingCodesState.loading,
            class_name=BUTTON,
        ),
        key=selection["id"],
        class_name="flex items-center gap-3 rounded-lg border border-white/10 bg-[#09090B] p-3",
    )


def saved_controls() -> rx.Component:
    return rx.el.details(
        rx.el.summary(
            "Import your private saved selections",
            class_name="cursor-pointer text-sm font-medium text-[#F4F4F5] focus-visible:outline-2 focus-visible:outline-[#EF233C]",
        ),
        rx.el.div(
            rx.el.p(
                "Add multiple legs. Each ID is reloaded and ownership checked on the server; duplicate IDs or equivalent exact legs are rejected. Imported sample legs remain fictional and cannot be used for real transfers.",
                class_name="flex-1 text-xs leading-5 text-zinc-400",
            ),
            rx.el.button(
                "Refresh saved",
                on_click=BookingCodesState.refresh_saved,
                disabled=BookingCodesState.loading,
                class_name=BUTTON,
            ),
            class_name="mt-3 flex flex-wrap items-start gap-3",
        ),
        rx.cond(
            BookingCodesState.selections.length() > 0,
            rx.el.div(
                rx.foreach(BookingCodesState.selections, saved_choice),
                class_name="mt-3 max-h-72 space-y-2 overflow-y-auto",
            ),
            rx.el.p(
                "No saved selections loaded. Refresh or use manual entry below.",
                class_name="mt-3 text-xs text-zinc-400",
            ),
        ),
        class_name=CARD,
    )


def entry_field(spec: dict[str, str]) -> rx.Component:
    return rx.el.div(
        rx.el.label(
            spec["label"],
            html_for=f"transfer-{spec['key']}",
            class_name="mb-1.5 block text-xs text-zinc-300",
        ),
        rx.el.input(
            id=f"transfer-{spec['key']}",
            name=spec["key"],
            default_value=BookingCodesState.draft[spec["key"]],
            key=BookingCodesState.draft[spec["key"]],
            placeholder=spec["hint"],
            max_length=200,
            class_name=INPUT,
        ),
    )


def note_field(spec: dict[str, str]) -> rx.Component:
    return rx.el.div(
        rx.el.label(
            spec["label"],
            html_for=f"transfer-{spec['key']}",
            class_name="mb-1.5 block text-xs text-zinc-300",
        ),
        rx.el.textarea(
            id=f"transfer-{spec['key']}",
            name=spec["key"],
            default_value=BookingCodesState.draft[spec["key"]],
            key=BookingCodesState.draft[spec["key"]],
            placeholder=spec["hint"],
            max_length=4000,
            rows=3,
            class_name=INPUT,
        ),
    )


def manual_entry() -> rx.Component:
    return rx.el.details(
        rx.el.summary(
            rx.cond(
                BookingCodesState.editing_id != "",
                "Edit draft leg · destination review resets",
                "Add manual leg",
            ),
            class_name="cursor-pointer text-sm font-medium text-[#F4F4F5] focus-visible:outline-2 focus-visible:outline-[#EF233C]",
        ),
        rx.el.p(
            "Manual entry is unverified. Verify category, event, exact market and settlement yourself. Editing event/market/line/outcome is a NEW changed selection, not a silently substituted market. Prices are optional; unknown prices remain unknown. Missing kickoff or settlement blocks confirmation.",
            class_name="mt-3 text-xs leading-5 text-zinc-400",
        ),
        rx.el.form(
            rx.el.div(
                rx.foreach(CORE_FIELDS, entry_field),
                class_name="grid gap-3 sm:grid-cols-2",
            ),
            rx.el.div(
                rx.el.label(
                    "Leg's original source bookmaker",
                    html_for="transfer-bookmaker",
                    class_name="mb-1.5 block text-xs text-zinc-300",
                ),
                rx.el.div(
                    rx.el.select(
                        rx.foreach(
                            BOOKMAKERS,
                            lambda book: rx.el.option(book, value=book),
                        ),
                        id="transfer-bookmaker",
                        name="bookmaker",
                        default_value=BookingCodesState.draft["bookmaker"],
                        key=BookingCodesState.form_version,
                        class_name="w-full appearance-none rounded-lg border border-white/15 bg-[#09090B] py-2.5 pl-3 pr-8 text-xs text-[#F4F4F5] focus:border-[#EF233C] focus:outline-hidden",
                    ),
                    rx.icon(
                        "chevron-down",
                        class_name="pointer-events-none absolute right-3 top-3 h-4 w-4 text-zinc-400",
                    ),
                    class_name="relative",
                ),
                class_name="mt-3",
            ),
            rx.el.div(
                rx.foreach(NOTE_FIELDS, note_field),
                class_name="mt-3 grid gap-3 sm:grid-cols-2",
            ),
            rx.el.div(
                rx.el.button(
                    rx.cond(
                        BookingCodesState.editing_id != "",
                        "Save draft edits",
                        "Add manual leg",
                    ),
                    type="submit",
                    class_name=PRIMARY,
                ),
                rx.el.button(
                    "Clear / cancel",
                    type="button",
                    on_click=BookingCodesState.cancel_edit,
                    class_name=BUTTON,
                ),
                class_name="mt-4 flex flex-wrap gap-2",
            ),
            on_submit=BookingCodesState.save_leg,
            key=BookingCodesState.form_version,
            class_name="mt-4",
        ),
        open=BookingCodesState.editing_id != "",
        class_name=CARD,
    )


def leg_card(leg: TransferLeg) -> rx.Component:
    return rx.el.article(
        rx.el.div(
            rx.el.h3(
                f"{leg['details']['home']} vs {leg['details']['away']}",
                class_name="text-sm font-semibold text-[#F4F4F5]",
            ),
            rx.el.span(
                leg["source_status"].upper(),
                class_name=rx.cond(
                    leg["source_status"] == "sample",
                    "w-fit rounded border border-red-400/40 bg-red-400/10 px-2 py-1 text-[10px] font-semibold text-red-300",
                    "w-fit rounded bg-white/5 px-2 py-1 text-[10px] text-zinc-300",
                ),
            ),
            class_name="flex flex-wrap items-center gap-2",
        ),
        rx.el.p(
            leg["status"], class_name="mt-2 text-xs font-medium text-zinc-200"
        ),
        rx.cond(
            leg["manual_edits"],
            rx.el.p(
                "Current edited details: MANUAL / UNVERIFIED. Original source data status retained above.",
                class_name="mt-2 text-[11px] text-zinc-300",
            ),
        ),
        rx.cond(
            leg["changed"],
            rx.el.p(
                "NEW CHANGED selection · manual edits — NOT the original equivalent market",
                class_name="mt-2 text-xs font-semibold text-red-300",
            ),
        ),
        rx.el.p(
            f"{leg['details']['competition']} · {leg['details']['category']} · {leg['details']['kickoff']}",
            class_name="mt-2 text-[11px] text-zinc-400",
        ),
        rx.el.p(
            f"{leg['details']['market']} / {leg['details']['outcome']} · Line: {leg['details']['line']} · Period: {leg['details']['period']}",
            class_name="mt-2 text-xs text-[#F4F4F5]",
        ),
        rx.el.p(
            f"Source: {leg['details']['bookmaker']} · {rx.cond(leg['details']['price'] != '', leg['details']['price'], 'Unknown odds')} · {leg['details']['observed']}",
            class_name="mt-2 text-[11px] text-zinc-400",
        ),
        rx.el.p(
            f"Destination: {BookingCodesState.destination} · {rx.cond(leg['details']['destination_price'] != '', leg['details']['destination_price'], 'Unknown odds')} · {leg['details']['destination_observed']} · ALWAYS manual/unverified",
            class_name="mt-1 text-[11px] text-zinc-300",
        ),
        rx.cond(
            leg["gaps"] != "",
            rx.el.p(
                leg["gaps"],
                class_name="mt-3 rounded-lg border border-white/10 bg-[#141416] p-3 text-[11px] leading-5 text-zinc-300",
            ),
        ),
        rx.el.details(
            rx.el.summary(
                "Settlement, evidence & original source",
                class_name="mt-3 cursor-pointer text-xs text-zinc-300 focus-visible:outline-2 focus-visible:outline-[#EF233C]",
            ),
            rx.el.p(
                f"Subject: {leg['details']['subject']} · Cards: {leg['details']['cards']} · Rules: {leg['details']['rules']}",
                class_name="mt-2 whitespace-pre-wrap text-xs leading-5 text-zinc-300",
            ),
            rx.el.p(
                f"Destination review notes: {leg['details']['evidence']}",
                class_name="mt-2 whitespace-pre-wrap text-xs leading-5 text-zinc-400",
            ),
            rx.el.p(
                f"Rationale: {leg['details']['rationale']}",
                class_name="mt-2 whitespace-pre-wrap text-xs leading-5 text-zinc-400",
            ),
            rx.el.pre(
                leg["original"].to_string(),
                class_name="mt-2 whitespace-pre-wrap break-all text-[10px] leading-5 text-zinc-400",
            ),
            rx.el.p(
                leg["provenance"],
                class_name="mt-2 whitespace-pre-wrap break-all text-[10px] leading-5 text-zinc-400",
            ),
            rx.cond(
                leg["chat"] != "",
                rx.el.a(
                    "View linked research",
                    href=f"/selections?chat={leg['chat']}",
                    class_name="mt-2 inline-block text-xs text-zinc-300 underline decoration-[#EF233C] focus-visible:outline-2 focus-visible:outline-[#EF233C]",
                ),
            ),
        ),
        rx.cond(
            leg["included"],
            rx.el.form(
                rx.el.label(
                    rx.el.input(
                        name="event",
                        type="checkbox",
                        required=True,
                        default_checked=leg["event_reviewed"],
                        key=leg["event_reviewed"],
                        class_name="mt-1 h-4 w-4 shrink-0 accent-[#EF233C]",
                    ),
                    "I checked exact home-away, competition, category and kickoff in the destination UI.",
                    class_name="flex items-start gap-2 text-[11px] leading-5 text-zinc-300",
                ),
                rx.el.label(
                    rx.el.input(
                        name="market",
                        type="checkbox",
                        required=True,
                        default_checked=leg["market_reviewed"],
                        key=leg["market_reviewed"],
                        class_name="mt-1 h-4 w-4 shrink-0 accent-[#EF233C]",
                    ),
                    "I checked exact market, line (or not applicable), outcome, period, subject and all card/settlement definitions. Not an approximate match.",
                    class_name="flex items-start gap-2 text-[11px] leading-5 text-zinc-300",
                ),
                rx.el.button(
                    "Confirm personal review", type="submit", class_name=BUTTON
                ),
                on_submit=lambda data: BookingCodesState.review_leg(
                    leg["id"], data
                ),
                class_name="mt-4 space-y-3 border-t border-white/10 pt-4",
            ),
            rx.el.p(
                f"Excluded reason: {leg['reason']}",
                class_name="mt-3 text-xs text-zinc-300",
            ),
        ),
        rx.el.div(
            rx.el.button(
                "Edit / enter changed alternative",
                on_click=BookingCodesState.edit_leg(leg["id"]),
                class_name=BUTTON,
            ),
            rx.el.button(
                "Mark market missing",
                on_click=BookingCodesState.mark_missing(leg["id"]),
                class_name=BUTTON,
            ),
            rx.cond(
                leg["changed"],
                rx.el.button(
                    "Revert original source details",
                    on_click=BookingCodesState.revert_leg(leg["id"]),
                    class_name=BUTTON,
                ),
            ),
            rx.el.button(
                rx.icon("trash-2", class_name="h-3.5 w-3.5"),
                "Remove draft leg",
                on_click=BookingCodesState.remove_leg(leg["id"]),
                class_name=BUTTON,
            ),
            class_name="mt-3 flex flex-wrap gap-2",
        ),
        rx.el.form(
            rx.cond(
                leg["included"],
                rx.el.div(
                    rx.el.label(
                        "Explicit exclusion reason",
                        html_for=f"exclude-{leg['id']}",
                        class_name="mb-1 block text-[11px] text-zinc-400",
                    ),
                    rx.el.input(
                        name="reason",
                        id=f"exclude-{leg['id']}",
                        default_value=leg["reason"],
                        key=leg["reason"],
                        max_length=500,
                        required=True,
                        placeholder="Missing market / started / personally excluded",
                        class_name=INPUT,
                    ),
                    class_name="min-w-0 flex-1",
                ),
            ),
            rx.el.button(
                rx.cond(
                    leg["included"], "Exclude leg", "Reinclude · review again"
                ),
                type="submit",
                class_name=BUTTON,
            ),
            on_submit=lambda data: BookingCodesState.set_inclusion(
                leg["id"], data
            ),
            class_name="mt-3 flex flex-wrap items-end gap-2",
        ),
        key=leg["id"],
        class_name="rounded-xl border border-white/10 bg-[#09090B] p-4",
    )


def support_inspector() -> rx.Component:
    return rx.el.section(
        rx.el.h2(
            "Operator support",
            class_name="text-sm font-semibold text-[#F4F4F5]",
        ),
        rx.el.div(
            rx.foreach(
                BOOKMAKERS,
                lambda book: rx.el.div(
                    rx.el.a(
                        book,
                        href=rx.Var.create(OFFICIAL_SITES)[book],
                        target="_blank",
                        rel="noopener noreferrer",
                        class_name="text-xs font-medium text-[#F4F4F5] underline decoration-[#EF233C] focus-visible:outline-2 focus-visible:outline-[#EF233C]",
                    ),
                    rx.el.p(
                        "Resolve / create / convert: unavailable without verified operator access",
                        class_name="mt-1 text-[11px] leading-5 text-zinc-400",
                    ),
                    class_name="border-b border-white/10 py-3 last:border-0",
                ),
            ),
            class_name="mt-1",
        ),
        rx.el.details(
            rx.el.summary(
                "Why manual only?",
                class_name="cursor-pointer text-xs text-zinc-300 focus-visible:outline-2 focus-visible:outline-[#EF233C]",
            ),
            rx.el.p(
                "No verified publicly documented legitimate booking-code APIs found for these operators. Bet9ja MarketWS WSDL odds reads returned 403 and expose no booking-code methods. Odds-API.io provides SportyBet/Bet9ja prices, not native slip resolution/creation; BetKing feed unsupported. No operator connection or automatic mapping is claimed. Unknown settlement data remains a gap until personally reviewed.",
                class_name="mt-2 text-[11px] leading-5 text-zinc-400",
            ),
        ),
        rx.el.button(
            "Native code generation · unsupported",
            on_click=BookingCodesState.native_code,
            class_name=BUTTON,
        ),
        class_name="space-y-3 rounded-xl border border-white/10 bg-[#141416] p-4 sm:p-5",
    )


def output_inspector() -> rx.Component:
    return rx.el.aside(
        rx.el.section(
            rx.el.div(
                rx.icon("list-checks", class_name="h-4 w-4 text-[#EF233C]"),
                rx.el.h2(
                    "Manual transfer checklist",
                    class_name="text-sm font-semibold text-[#F4F4F5]",
                ),
                class_name="flex items-center gap-2",
            ),
            rx.el.p(
                "NOT a destination bookmaker booking code",
                class_name="mt-2 text-xs font-medium text-red-300",
            ),
            rx.el.p(
                f"{BookingCodesState.counts['included']} included · {BookingCodesState.counts['confirmed']} personally confirmed · {BookingCodesState.counts['excluded']} excluded · {BookingCodesState.counts['unresolved']} unresolved",
                class_name="mt-4 text-xs leading-6 text-zinc-300",
            ),
            rx.el.div(
                rx.foreach(
                    BookingCodesState.reviewed_legs,
                    lambda leg: rx.el.div(
                        rx.el.p(
                            f"{rx.cond(leg['included'], 'Included', 'Excluded')} · {leg['details']['home']} vs {leg['details']['away']}",
                            class_name="text-[11px] font-medium text-zinc-200",
                        ),
                        rx.el.p(
                            f"{leg['details']['market']} / {leg['details']['outcome']} {leg['details']['line']} · {leg['status']}",
                            class_name="mt-1 text-[10px] leading-5 text-zinc-400",
                        ),
                        rx.cond(
                            ~leg["included"],
                            rx.el.p(
                                leg["reason"],
                                class_name="mt-1 text-[10px] text-zinc-400",
                            ),
                        ),
                        class_name="border-b border-white/10 py-2 last:border-0",
                    ),
                ),
                class_name="mt-3 max-h-64 overflow-y-auto",
            ),
            rx.el.button(
                "Prepare manual transfer",
                on_click=BookingCodesState.prepare_manual_transfer,
                disabled=BookingCodesState.loading,
                class_name="mt-4 inline-flex w-full items-center justify-center rounded-lg bg-[#EF233C] px-4 py-3 text-xs font-semibold text-white hover:bg-[#D91F36] disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-[#EF233C]",
            ),
            rx.el.p(
                rx.cond(
                    BookingCodesState.total_odds != "",
                    f"Combined decimal odds: {BookingCodesState.total_odds} · manual/unverified",
                    "Combined odds unavailable until prepared with all included reviews and current valid destination prices.",
                ),
                class_name="mt-3 text-xs leading-5 text-zinc-300",
            ),
            rx.cond(
                BookingCodesState.output != "",
                rx.el.pre(
                    BookingCodesState.output,
                    class_name="mt-4 max-h-[480px] overflow-y-auto whitespace-pre-wrap break-words rounded-lg border border-white/10 bg-[#09090B] p-3 text-[11px] leading-5 text-zinc-300",
                ),
                rx.el.p(
                    "Checklist preview appears here after preparation. Unresolved details stay explicit; no code is invented.",
                    class_name="mt-4 text-xs leading-5 text-zinc-400",
                ),
            ),
            rx.el.div(
                rx.el.button(
                    rx.icon("copy", class_name="h-3.5 w-3.5"),
                    "Copy text",
                    on_click=BookingCodesState.copy_checklist,
                    disabled=BookingCodesState.output == "",
                    class_name=BUTTON,
                ),
                rx.el.button(
                    rx.icon("download", class_name="h-3.5 w-3.5"),
                    ".txt download",
                    on_click=BookingCodesState.download_checklist,
                    disabled=BookingCodesState.output == "",
                    class_name=BUTTON,
                ),
                class_name="mt-3 flex flex-wrap gap-2",
            ),
            rx.el.a(
                f"Open {BookingCodesState.destination} official site",
                href=BookingCodesState.destination_site,
                target="_blank",
                rel="noopener noreferrer",
                class_name="mt-4 block text-xs text-[#F4F4F5] underline decoration-[#EF233C] focus-visible:outline-2 focus-visible:outline-[#EF233C]",
            ),
            rx.el.p(
                "Manually add and recheck selections in the operator UI. No bets placed. Same-event legs may be correlated or disallowed; no independent combined-return claim. Extra legs raise risk; no guarantees.",
                class_name="mt-3 text-[11px] leading-5 text-zinc-400",
            ),
            rx.el.a(
                "Single-selection stake limits → Selections",
                href="/selections",
                class_name="mt-3 block text-xs text-zinc-300 underline decoration-[#EF233C] focus-visible:outline-2 focus-visible:outline-[#EF233C]",
            ),
            class_name=CARD,
        ),
        support_inspector(),
        class_name="min-w-0 space-y-4 lg:col-span-4",
    )


def booking_codes_workspace() -> rx.Component:
    return rx.el.div(
        navigation(active="booking-codes"),
        rx.el.main(
            rx.el.h1(
                "Booking codes",
                class_name="text-2xl font-semibold tracking-tight text-[#F4F4F5]",
            ),
            rx.el.p(
                "Review an exact selection transfer. Native code conversion is unsupported; a useful manual checklist works here.",
                class_name="mb-5 mt-2 text-sm leading-6 text-zinc-400",
            ),
            conversion_controls(),
            rx.cond(
                BookingCodesState.loading,
                rx.el.p(
                    "Loading your private saved selections…",
                    role="status",
                    class_name="mt-4 animate-pulse rounded-lg border border-white/10 bg-[#141416] p-3 text-xs text-zinc-300",
                ),
            ),
            rx.cond(
                BookingCodesState.error != "",
                rx.el.p(
                    BookingCodesState.error,
                    role="alert",
                    class_name="mt-4 rounded-lg border border-red-400/20 bg-red-400/5 p-3 text-xs leading-5 text-red-300",
                ),
            ),
            rx.cond(
                BookingCodesState.notice != "",
                rx.el.p(
                    BookingCodesState.notice,
                    role="status",
                    class_name="mt-4 rounded-lg border border-white/10 bg-[#141416] p-3 text-xs leading-5 text-zinc-300",
                ),
            ),
            rx.el.div(
                rx.el.div(
                    rx.el.p(
                        "Draft; saved research selections remain stored, transfer edits reset on reload. Maximum 50 local legs.",
                        class_name="text-[11px] leading-5 text-zinc-400",
                    ),
                    saved_controls(),
                    manual_entry(),
                    rx.el.section(
                        rx.el.h2(
                            "Selection-leg review",
                            class_name="mb-4 text-base font-semibold text-[#F4F4F5]",
                        ),
                        rx.cond(
                            BookingCodesState.legs.length() > 0,
                            rx.el.div(
                                rx.foreach(
                                    BookingCodesState.reviewed_legs, leg_card
                                ),
                                class_name="space-y-3",
                            ),
                            rx.el.div(
                                rx.icon(
                                    "list-plus",
                                    class_name="mb-3 h-5 w-5 text-zinc-400",
                                ),
                                rx.el.p(
                                    "No transfer legs yet",
                                    class_name="text-sm text-zinc-200",
                                ),
                                rx.el.p(
                                    "Import owned selections or add a manual leg. Your code is not parsed and no sample legs are seeded.",
                                    class_name="mt-2 text-xs leading-5 text-zinc-400",
                                ),
                                class_name="rounded-lg border border-dashed border-white/15 p-5",
                            ),
                        ),
                        class_name=CARD,
                    ),
                    class_name="min-w-0 space-y-4 lg:col-span-8",
                ),
                output_inspector(),
                class_name="mt-5 grid w-full grid-cols-1 items-start gap-5 lg:grid-cols-12",
            ),
            class_name="min-w-0 w-full flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8",
        ),
        class_name="flex h-dvh w-full flex-col overflow-hidden bg-[#09090B] font-['Inter'] text-[#F4F4F5]",
    )
