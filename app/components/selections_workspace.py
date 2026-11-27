import reflex as rx

from app.components.navigation import navigation
from app.components.research_workspace import message_card
from app.odds_service import BOOKMAKERS, FixtureView, QuoteView, SelectionView
from app.states.selections_state import SelectionsState

BUTTON = "inline-flex items-center justify-center gap-2 rounded-lg border border-white/15 bg-[#141416] px-3 py-2 text-xs font-medium text-[#F4F4F5] hover:border-white/30 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-[#EF233C]"
PRIMARY = "inline-flex items-center justify-center gap-2 rounded-lg bg-[#EF233C] px-4 py-2.5 text-xs font-semibold text-white hover:bg-[#D91F36] disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#EF233C]"
INPUT = "w-full min-w-0 rounded-lg border border-white/15 bg-[#09090B] px-3 py-2.5 text-xs text-[#F4F4F5] placeholder:text-zinc-500 focus:border-[#EF233C] focus:outline-hidden"
CARD = "rounded-xl border border-white/10 bg-[#141416] p-4 sm:p-5"


def field(
    name: str, label: str, placeholder: str = "", required: bool = False
) -> rx.Component:
    return rx.el.div(
        rx.el.label(
            label,
            html_for=name,
            class_name="mb-1.5 block text-xs text-zinc-300",
        ),
        rx.el.input(
            id=name,
            name=name,
            default_value=SelectionsState.draft[name],
            key=SelectionsState.draft[name],
            placeholder=placeholder,
            required=required,
            max_length=4000,
            class_name=INPUT,
        ),
    )


def chat_select(identity: str, current: rx.Var[str] | str) -> rx.Component:
    return rx.el.div(
        rx.el.label(
            "Linked research (optional)",
            html_for=identity,
            class_name="mb-1.5 block text-xs text-zinc-300",
        ),
        rx.el.div(
            rx.el.select(
                rx.el.option("No linked chat", value=""),
                rx.foreach(
                    SelectionsState.chats,
                    lambda chat: rx.el.option(chat["title"], value=chat["id"]),
                ),
                id=identity,
                name="chat",
                default_value=current,
                key=current,
                class_name="w-full appearance-none rounded-lg border border-white/15 bg-[#09090B] py-2.5 pl-3 pr-8 text-xs text-[#F4F4F5] focus:border-[#EF233C] focus:outline-hidden",
            ),
            rx.icon(
                "chevron-down",
                class_name="pointer-events-none absolute right-3 top-3 h-4 w-4 text-zinc-400",
            ),
            class_name="relative",
        ),
    )


def research_context() -> rx.Component:
    return rx.el.details(
        rx.el.summary(
            rx.icon("book-open", class_name="h-4 w-4 text-[#EF233C]"),
            rx.cond(
                SelectionsState.linked_title != "",
                f"Linked research · {SelectionsState.linked_title}",
                "Link your personally reviewed research",
            ),
            class_name="flex cursor-pointer items-center gap-2 text-xs font-medium text-[#F4F4F5] focus-visible:outline-2 focus-visible:outline-[#EF233C]",
        ),
        rx.el.form(
            chat_select("context-chat", SelectionsState.linked_chat),
            rx.el.button(
                "Show research & sources",
                type="submit",
                disabled=SelectionsState.loading,
                class_name=BUTTON,
            ),
            on_submit=SelectionsState.link_research,
            class_name="mt-4 flex flex-col items-start gap-3 sm:flex-row sm:items-end [&>div]:flex-1",
        ),
        rx.el.p(
            "Linking a chat is not evidence that a pick is supported. Cite your reviewed sources in the rationale, record gaps, or choose no bet.",
            class_name="mt-3 text-xs leading-5 text-zinc-400",
        ),
        rx.cond(
            SelectionsState.messages.length() > 0,
            rx.el.div(
                rx.foreach(SelectionsState.messages, message_card),
                class_name="mt-4 max-h-[460px] space-y-3 overflow-y-auto",
            ),
            rx.el.p(
                "No research context selected. Sample research has no substantiating sources.",
                class_name="mt-3 text-xs text-zinc-400",
            ),
        ),
        class_name=CARD,
    )


def connection_card() -> rx.Component:
    return rx.el.details(
        rx.el.summary(
            "Odds feed connection",
            class_name="cursor-pointer text-xs font-medium text-[#F4F4F5] focus-visible:outline-2 focus-visible:outline-[#EF233C]",
        ),
        rx.el.p(
            rx.cond(
                SelectionsState.feed_available,
                "A live feed credential is connected. Access and bookmaker coverage are validated on each request.",
                "No live odds credential is connected. Manual prices work now; the explicit demo is separate from your real fixture.",
            ),
            class_name="mt-3 text-xs leading-5 text-zinc-400",
        ),
        rx.el.p(
            "Connect your Odds-API.io credential using the secure service-credentials settings, not a research message. SportyBet and Bet9ja require feed subscription access. BetKing has no verified feed here. OpenAI access is separate and powers research only.",
            class_name="mt-2 text-xs leading-5 text-zinc-400",
        ),
        class_name="rounded-xl border border-white/10 bg-[#141416] p-4",
    )


def fixture_item(fixture: FixtureView) -> rx.Component:
    return rx.el.button(
        rx.el.span(
            f"{fixture['home']} vs {fixture['away']}",
            class_name="block text-xs font-medium text-[#F4F4F5]",
        ),
        rx.el.span(
            f"{fixture['competition']} · {fixture['kickoff']}",
            class_name="mt-1 block text-[11px] text-zinc-400",
        ),
        rx.el.span(
            f"Event {fixture['id']} · {fixture['status']}",
            class_name="mt-1 block text-[10px] text-zinc-400",
        ),
        rx.cond(
            fixture["replacement"] != "",
            rx.el.span(
                f"Replacement: {fixture['replacement']} · select separately",
                class_name="block text-[11px] text-amber-300",
            ),
        ),
        on_click=SelectionsState.choose_fixture(fixture["id"]),
        disabled=SelectionsState.fetching,
        key=fixture["id"],
        class_name="w-full rounded-lg border border-white/10 bg-[#09090B] p-3 text-left hover:border-[#EF233C]/60 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-[#EF233C]",
    )


def live_search() -> rx.Component:
    return rx.el.div(
        rx.el.form(
            rx.el.div(
                rx.el.label(
                    "From (UTC)",
                    html_for="search-from",
                    class_name="mb-1.5 block text-xs text-zinc-300",
                ),
                rx.el.input(
                    id="search-from",
                    name="from",
                    type="datetime-local",
                    default_value=SelectionsState.search_start,
                    key=SelectionsState.search_start,
                    required=True,
                    class_name=INPUT,
                ),
            ),
            rx.el.div(
                rx.el.label(
                    "To (UTC, maximum 7 days)",
                    html_for="search-to",
                    class_name="mb-1.5 block text-xs text-zinc-300",
                ),
                rx.el.input(
                    id="search-to",
                    name="to",
                    type="datetime-local",
                    default_value=SelectionsState.search_end,
                    key=SelectionsState.search_end,
                    required=True,
                    class_name=INPUT,
                ),
            ),
            rx.el.button(
                rx.icon("search", class_name="h-3.5 w-3.5"),
                "Find fixtures",
                type="submit",
                disabled=SelectionsState.fetching,
                class_name=BUTTON,
            ),
            on_submit=SelectionsState.search,
            class_name="grid items-end gap-3 sm:grid-cols-[1fr_1fr_auto]",
        ),
        rx.el.p(
            SelectionsState.search_notice,
            class_name="mt-3 text-[11px] leading-5 text-zinc-400",
        ),
        rx.cond(
            SelectionsState.fixtures.length() > 0,
            rx.el.div(
                rx.el.label(
                    "Filter these results (not automatic fixture matching)",
                    html_for="fixture-filter",
                    class_name="mb-1.5 block text-xs text-zinc-300",
                ),
                rx.el.input(
                    id="fixture-filter",
                    default_value=SelectionsState.filter_text,
                    on_change=SelectionsState.filter_fixtures.debounce(500),
                    placeholder="Exact clubs / competition; confirm category and date",
                    class_name=INPUT,
                ),
                rx.el.div(
                    rx.foreach(SelectionsState.filtered_fixtures, fixture_item),
                    class_name="mt-3 grid max-h-64 gap-2 overflow-y-auto sm:grid-cols-2",
                ),
                class_name="mt-4",
            ),
        ),
    )


def quote_row(quote: QuoteView) -> rx.Component:
    return rx.el.tr(
        rx.el.td(
            rx.el.p(
                quote["bookmaker"], class_name="font-medium text-[#F4F4F5]"
            ),
            rx.el.span(
                quote["status"].upper(),
                class_name="mt-1 inline-block w-fit rounded bg-white/5 px-1.5 py-0.5 text-[9px] text-zinc-300",
            ),
            class_name="px-3 py-3 align-top",
        ),
        rx.el.td(
            rx.el.p(
                f"{quote['market']} · {quote['outcome']} {quote['line']}",
                class_name="text-zinc-200",
            ),
            rx.el.p(
                f"Period: {quote['period']} · Subject: {quote['subject']}",
                class_name="mt-1 text-[10px] text-zinc-400",
            ),
            rx.el.details(
                rx.el.summary(
                    "Labels & settlement",
                    class_name="mt-1 cursor-pointer text-[10px] text-zinc-300 focus-visible:outline-2 focus-visible:outline-[#EF233C]",
                ),
                rx.el.p(
                    quote["note"],
                    class_name="mt-1 max-w-xs text-[10px] leading-4 text-zinc-400",
                ),
                rx.el.p(
                    f"{quote['cards']} · {quote['rules']}",
                    class_name="mt-1 text-[10px] text-zinc-400",
                ),
                rx.el.pre(
                    quote["raw"],
                    class_name="mt-1 max-w-xs whitespace-pre-wrap break-all text-[10px] text-zinc-400",
                ),
            ),
            class_name="min-w-[200px] px-3 py-3 align-top",
        ),
        rx.el.td(
            rx.el.p(
                rx.cond(quote["price"] != "", quote["price"], "Unavailable"),
                class_name="text-sm font-semibold text-[#F4F4F5]",
            ),
            rx.cond(
                quote["highest"],
                rx.el.span(
                    "Highest decimal price",
                    class_name="mt-1 inline-block w-fit rounded bg-[#EF233C]/10 px-1.5 py-1 text-[9px] text-red-300",
                ),
            ),
            class_name="px-3 py-3 align-top",
        ),
        rx.el.td(
            rx.el.p(quote["freshness"], class_name="text-[10px] text-zinc-300"),
            rx.el.p(
                quote["observed"], class_name="mt-1 text-[10px] text-zinc-400"
            ),
            rx.cond(
                quote["url"] != "",
                rx.el.a(
                    "Operator source",
                    href=quote["url"],
                    target="_blank",
                    rel="noopener noreferrer",
                    class_name="mt-1 block text-[10px] text-zinc-300 underline decoration-[#EF233C] focus-visible:outline-2 focus-visible:outline-[#EF233C]",
                ),
            ),
            class_name="px-3 py-3 align-top",
        ),
        rx.el.td(
            rx.el.button(
                rx.cond(
                    SelectionsState.chosen_quote == quote["id"],
                    "Selected",
                    "Choose",
                ),
                on_click=SelectionsState.choose_quote(quote["id"]),
                disabled=~quote["eligible"]
                | SelectionsState.saving
                | SelectionsState.fetching,
                class_name=BUTTON,
            ),
            class_name="px-3 py-3 align-top",
        ),
        key=quote["id"],
        class_name="border-b border-white/10 odd:bg-[#09090B]/40 hover:bg-white/5",
    )


def comparison() -> rx.Component:
    return rx.el.section(
        rx.el.div(
            rx.el.h2(
                "Compare exact prices",
                class_name="text-base font-semibold text-[#F4F4F5]",
            ),
            rx.el.div(
                rx.el.button(
                    "Live / manual",
                    on_click=SelectionsState.set_demo(False),
                    aria_pressed=~SelectionsState.demo,
                    disabled=SelectionsState.fetching | SelectionsState.saving,
                    class_name=BUTTON,
                ),
                rx.el.button(
                    "Fictional demo",
                    on_click=SelectionsState.set_demo(True),
                    aria_pressed=SelectionsState.demo,
                    disabled=SelectionsState.fetching | SelectionsState.saving,
                    class_name=BUTTON,
                ),
                class_name="flex gap-2",
            ),
            class_name="mb-4 flex flex-wrap items-center justify-between gap-3",
        ),
        rx.cond(
            SelectionsState.demo,
            rx.el.div(
                rx.el.p(
                    "Sample odds — connect an odds feed for live prices",
                    class_name="text-xs font-semibold text-[#F4F4F5]",
                ),
                rx.el.p(
                    "Northbridge FC vs Riverside FC · fictional demonstration league · 01 Aug 2030, 15:00 UTC. Fixed sample observations: 01 Jan 2025, 12:00 UTC. Not odds for your real fixture or verified bookmaker coverage.",
                    class_name="mt-2 text-xs leading-5 text-zinc-400",
                ),
                role="status",
                class_name="mb-4 rounded-lg border border-[#EF233C]/30 bg-[#09090B] p-3",
            ),
            live_search(),
        ),
        rx.cond(
            SelectionsState.fetching,
            rx.el.div(
                rx.icon(
                    "loader-circle",
                    class_name="h-4 w-4 animate-spin text-[#EF233C]",
                ),
                "Checking exact fixture & feed coverage…",
                role="status",
                class_name="mt-4 flex items-center gap-2 text-xs text-zinc-400",
            ),
        ),
        rx.cond(
            SelectionsState.fixture_label != "",
            rx.el.p(
                SelectionsState.fixture_label,
                class_name="mb-3 mt-5 text-xs font-medium text-zinc-200",
            ),
        ),
        rx.cond(
            SelectionsState.quotes.length() > 0,
            rx.el.div(
                rx.el.div(
                    rx.el.table(
                        rx.el.thead(
                            rx.el.tr(
                                rx.foreach(
                                    [
                                        "Bookmaker",
                                        "Exact market / outcome",
                                        "Decimal price",
                                        "Market observation",
                                        "",
                                    ],
                                    lambda label: rx.el.th(
                                        label,
                                        class_name="px-3 py-3 text-left text-[10px] font-medium text-zinc-400",
                                    ),
                                )
                            )
                        ),
                        rx.el.tbody(
                            rx.foreach(SelectionsState.quotes, quote_row)
                        ),
                        class_name="table-auto w-full text-xs",
                    ),
                    class_name="max-h-[420px] overflow-auto",
                ),
                class_name="mt-3 overflow-hidden rounded-lg border border-white/10",
            ),
            rx.el.p(
                "Search and explicitly select a fixture, enable the fictional demo, or enter a reviewed manual selection below. No bet is always an option.",
                class_name="mt-4 text-xs leading-5 text-zinc-400",
            ),
        ),
        rx.el.div(
            rx.foreach(
                SelectionsState.bookmaker_coverage,
                lambda book: rx.el.div(
                    rx.el.p(
                        book["bookmaker"],
                        class_name="text-xs font-medium text-zinc-200",
                    ),
                    rx.el.p(
                        book["status"],
                        class_name="mt-1 text-[10px] leading-4 text-zinc-400",
                    ),
                    class_name="min-w-0 rounded-lg border border-dashed border-white/15 p-3",
                ),
            ),
            class_name="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-3",
        ),
        rx.el.p(
            "Price comparisons require identical event, market, outcome, line, period and subject; known settlement definitions must also match. Unknown rules remain a gap, not confirmed equivalence. Card-rule gaps prevent a highest-price comparison across books. Missing markets are not offered, not zero odds. Prices alone do not reveal win probability. Highest decimal price is not a guaranteed pick.",
            class_name="mt-3 text-[11px] leading-5 text-zinc-400",
        ),
        rx.cond(SelectionsState.chosen_quote != "", quote_save_form()),
        class_name=CARD,
    )


def quote_save_form() -> rx.Component:
    return rx.el.form(
        rx.el.p(
            f"Chosen: {SelectionsState.chosen_label}",
            class_name="text-xs font-medium text-[#F4F4F5]",
        ),
        rx.el.div(
            rx.el.label(
                "Personally reviewed rationale / cited sources / evidence gaps",
                html_for="quote-rationale",
                class_name="mb-1.5 block text-xs text-zinc-300",
            ),
            rx.el.textarea(
                id="quote-rationale",
                name="rationale",
                required=True,
                max_length=4000,
                placeholder="Cite reviewed evidence; do not infer support from a linked chat. Use no bet if evidence is insufficient.",
                class_name=INPUT,
            ),
        ),
        chat_select("quote-chat", SelectionsState.linked_chat),
        rx.el.div(
            rx.el.label(
                "Operator settlement notes (unverified user notes)",
                html_for="quote-rules",
                class_name="mb-1.5 block text-xs text-zinc-300",
            ),
            rx.el.input(
                id="quote-rules",
                name="rules",
                placeholder="90 min / extra time / cards vs points / second yellows / reds / bench",
                class_name=INPUT,
            ),
        ),
        rx.el.label(
            rx.el.input(
                name="reviewed",
                type="checkbox",
                required=True,
                class_name="h-4 w-4 accent-[#EF233C]",
            ),
            "I personally reviewed this selection and any settlement gaps. No guarantee or automatic transfer.",
            class_name="flex items-start gap-2 text-[11px] leading-5 text-zinc-300",
        ),
        rx.el.button(
            "Save chosen price",
            type="submit",
            disabled=SelectionsState.saving | SelectionsState.fetching,
            class_name=PRIMARY,
        ),
        on_submit=SelectionsState.save_quote,
        class_name="mt-5 space-y-3 border-t border-white/10 pt-4",
    )


def manual_form() -> rx.Component:
    return rx.el.details(
        rx.el.summary(
            rx.cond(
                SelectionsState.editing_id != "",
                "Edit saved selection · manual details",
                "Add manual selection / record no bet",
            ),
            class_name="cursor-pointer text-sm font-medium text-[#F4F4F5] focus-visible:outline-2 focus-visible:outline-[#EF233C]",
        ),
        rx.el.p(
            "All entered prices and settlement notes are MANUAL unverified. Enter a full UTC timestamp with Z (or an explicit offset). Leave odds blank to record no bet. Sample edits remain sample; edited feed selections become manual.",
            class_name="mt-3 text-xs leading-5 text-zinc-400",
        ),
        rx.el.form(
            rx.el.div(
                field(
                    "home",
                    "Exact home team / category",
                    "Club name including women / U21",
                    True,
                ),
                field(
                    "away",
                    "Exact away team / category",
                    "Club name including women / U21",
                    True,
                ),
                field("competition", "Competition", "Exact competition", True),
                field(
                    "kickoff",
                    "Kickoff (timezone required)",
                    "2026-08-01T15:00:00Z",
                    True,
                ),
                field(
                    "market",
                    "Exact market",
                    "ML / Totals / Total cards / Booking points",
                    True,
                ),
                field(
                    "outcome",
                    "Outcome / no bet",
                    "Home / Over / No bet — insufficient evidence",
                    True,
                ),
                field(
                    "line",
                    "Exact line (if applicable)",
                    "2.5 or exact split-line label",
                ),
                field(
                    "period", "Period", "match / first half / 90 minutes", True
                ),
                field("subject", "Subject (team / player, if applicable)"),
                field(
                    "cards",
                    "Card / booking-point definition",
                    "Second yellows, reds, bench exclusions",
                ),
                field(
                    "rules",
                    "Settlement notes",
                    "Check operator rules; unknown is an evidence gap",
                ),
                rx.el.div(
                    rx.el.label(
                        "Bookmaker",
                        html_for="manual-bookmaker",
                        class_name="mb-1.5 block text-xs text-zinc-300",
                    ),
                    rx.el.div(
                        rx.el.select(
                            rx.foreach(
                                BOOKMAKERS,
                                lambda book: rx.el.option(book, value=book),
                            ),
                            id="manual-bookmaker",
                            name="bookmaker",
                            default_value=SelectionsState.draft["bookmaker"],
                            key=SelectionsState.draft["bookmaker"],
                            class_name="w-full appearance-none rounded-lg border border-white/15 bg-[#09090B] py-2.5 pl-3 pr-8 text-xs text-[#F4F4F5] focus:border-[#EF233C] focus:outline-hidden",
                        ),
                        rx.icon(
                            "chevron-down",
                            class_name="pointer-events-none absolute right-3 top-3 h-4 w-4 text-zinc-400",
                        ),
                        class_name="relative",
                    ),
                ),
                field(
                    "price",
                    "Manual decimal odds (optional)",
                    "Greater than 1; blank for no bet",
                ),
                field(
                    "observed",
                    "Price observed at (timezone required)",
                    "2026-08-01T12:30:00Z",
                ),
                chat_select("manual-chat", SelectionsState.draft["chat"]),
                field(
                    "rationale",
                    "Reviewed rationale / cited sources / gaps",
                    "Explain evidence or the no-bet decision",
                    True,
                ),
                class_name="grid gap-3 sm:grid-cols-2",
            ),
            rx.el.div(
                rx.el.button(
                    rx.cond(
                        SelectionsState.editing_id != "",
                        "Save manual changes",
                        "Save manual selection",
                    ),
                    type="submit",
                    disabled=SelectionsState.saving,
                    class_name=PRIMARY,
                ),
                rx.el.button(
                    "Clear / cancel edit",
                    type="button",
                    on_click=SelectionsState.cancel_edit,
                    disabled=SelectionsState.saving,
                    class_name=BUTTON,
                ),
                class_name="mt-4 flex flex-wrap gap-2",
            ),
            on_submit=SelectionsState.save_manual,
            class_name="mt-4",
        ),
        open=SelectionsState.editing_id != "",
        class_name=CARD,
    )


def stake_calculator() -> rx.Component:
    return rx.el.aside(
        rx.el.div(
            rx.icon("calculator", class_name="h-4 w-4 text-[#EF233C]"),
            rx.el.h2(
                "Bankroll & returns",
                class_name="text-base font-semibold text-[#F4F4F5]",
            ),
            class_name="flex items-center gap-2",
        ),
        rx.el.p(
            "Single-selection calculation · NGN",
            class_name="mt-2 text-xs text-zinc-400",
        ),
        rx.el.p(
            rx.cond(
                SelectionsState.calculator_context != "",
                SelectionsState.calculator_context,
                "Choose a comparison row or use a saved selection. Save a manual price first to calculate it.",
            ),
            class_name="mt-4 rounded-lg border border-white/10 bg-[#09090B] p-3 text-xs leading-5 text-zinc-300",
        ),
        rx.el.form(
            rx.el.div(
                rx.el.label(
                    "Bankroll (NGN)",
                    html_for="bankroll",
                    class_name="mb-1.5 block text-xs text-zinc-300",
                ),
                rx.el.input(
                    id="bankroll",
                    name="bankroll",
                    type="number",
                    step="0.01",
                    min="0.01",
                    required=True,
                    default_value=SelectionsState.bankroll,
                    key=SelectionsState.bankroll,
                    placeholder="e.g. 50,000 (enter 50000)",
                    class_name=INPUT,
                ),
            ),
            rx.el.div(
                rx.el.label(
                    "Risk limit (%) · default 1 · maximum 2",
                    html_for="risk",
                    class_name="mb-1.5 block text-xs text-zinc-300",
                ),
                rx.el.input(
                    id="risk",
                    name="risk",
                    type="number",
                    step="0.01",
                    min="0.01",
                    max="2",
                    required=True,
                    default_value=SelectionsState.risk,
                    key=SelectionsState.risk,
                    class_name=INPUT,
                ),
            ),
            rx.el.div(
                rx.el.label(
                    "Stake (NGN, optional)",
                    html_for="stake",
                    class_name="mb-1.5 block text-xs text-zinc-300",
                ),
                rx.el.input(
                    id="stake",
                    name="stake",
                    type="number",
                    step="0.01",
                    min="0.01",
                    default_value=SelectionsState.stake,
                    key=SelectionsState.stake,
                    placeholder="Blank uses suggested maximum",
                    class_name=INPUT,
                ),
            ),
            rx.el.button(
                "Calculate potential return", type="submit", class_name=PRIMARY
            ),
            on_submit=SelectionsState.calculate_return,
            class_name="mt-4 space-y-4",
        ),
        rx.cond(
            SelectionsState.calculator_error != "",
            rx.el.p(
                SelectionsState.calculator_error,
                role="alert",
                class_name="mt-3 text-xs leading-5 text-red-300",
            ),
        ),
        rx.cond(
            SelectionsState.result["gross"] != "",
            rx.el.dl(
                rx.el.div(
                    rx.el.dt(
                        "Suggested maximum", class_name="text-xs text-zinc-400"
                    ),
                    rx.el.dd(
                        SelectionsState.result["maximum"],
                        class_name="text-sm font-semibold text-[#F4F4F5]",
                    ),
                    class_name="flex justify-between gap-2",
                ),
                rx.el.div(
                    rx.el.dt("Stake", class_name="text-xs text-zinc-400"),
                    rx.el.dd(
                        SelectionsState.result["stake"],
                        class_name="text-sm text-[#F4F4F5]",
                    ),
                    class_name="flex justify-between gap-2",
                ),
                rx.el.div(
                    rx.el.dt(
                        "Potential gross return",
                        class_name="text-xs text-zinc-400",
                    ),
                    rx.el.dd(
                        SelectionsState.result["gross"],
                        class_name="text-lg font-semibold text-[#F4F4F5]",
                    ),
                    class_name="flex items-center justify-between gap-2",
                ),
                rx.el.div(
                    rx.el.dt(
                        "Potential profit", class_name="text-xs text-zinc-400"
                    ),
                    rx.el.dd(
                        SelectionsState.result["profit"],
                        class_name="text-sm text-[#F4F4F5]",
                    ),
                    class_name="flex justify-between gap-2",
                ),
                class_name="mt-5 space-y-3 border-t border-white/10 pt-5",
            ),
        ),
        rx.el.p(
            "Rule-based maximum = bankroll × risk %. The conservative default is 1%, not a confidence score, Kelly strategy or optimal-stake claim. You may use less; never more than 2%.",
            class_name="mt-5 text-[11px] leading-5 text-zinc-400",
        ),
        rx.el.p(
            "Gross return = stake × decimal odds; profit = gross return − stake, only if the selection wins under the operator’s settlement rules. A loss can lose the entire stake. Taxes/fees are not included.",
            class_name="mt-3 text-[11px] leading-5 text-zinc-400",
        ),
        rx.el.p(
            "18+ · Only risk money you can afford to lose. No guaranteed picks. No bets are placed by Sport Analyst.",
            class_name="mt-3 text-[11px] leading-5 text-zinc-300",
        ),
        class_name="h-fit rounded-xl border border-white/10 bg-[#141416] p-4 sm:p-5",
    )


def saved_item(selection: SelectionView) -> rx.Component:
    return rx.el.article(
        rx.el.div(
            rx.el.div(
                rx.el.div(
                    rx.el.h3(
                        f"{selection['home']} vs {selection['away']}",
                        class_name="text-sm font-medium text-[#F4F4F5]",
                    ),
                    rx.el.span(
                        selection["status"].upper(),
                        class_name="w-fit rounded bg-white/5 px-2 py-1 text-[10px] text-zinc-300",
                    ),
                    class_name="flex flex-wrap items-center gap-2",
                ),
                rx.el.p(
                    f"{selection['competition']} · {selection['kickoff']}",
                    class_name="mt-1 text-[11px] text-zinc-400",
                ),
                rx.el.p(
                    f"{selection['bookmaker']} · {selection['market']} / {selection['outcome']} {selection['line']} · {selection['period']}",
                    class_name="mt-2 text-xs text-zinc-200",
                ),
                class_name="min-w-0 flex-1",
            ),
            rx.el.div(
                rx.el.p(
                    rx.cond(
                        selection["price"] != "",
                        f"Decimal {selection['price']}",
                        "No odds / no-bet record",
                    ),
                    class_name="text-sm font-semibold text-[#F4F4F5]",
                ),
                rx.el.p(
                    selection["freshness"],
                    class_name="mt-1 text-[10px] text-zinc-400",
                ),
                class_name="shrink-0 sm:text-right",
            ),
            class_name="flex flex-col justify-between gap-3 sm:flex-row",
        ),
        rx.el.details(
            rx.el.summary(
                "Rationale, source & settlement",
                class_name="mt-3 cursor-pointer text-[11px] text-zinc-300 focus-visible:outline-2 focus-visible:outline-[#EF233C]",
            ),
            rx.el.p(
                selection["rationale"],
                class_name="mt-2 whitespace-pre-wrap text-xs leading-5 text-zinc-300",
            ),
            rx.el.p(
                f"Subject: {selection['subject']} · Definition: {selection['cards']} · Settlement: {selection['rules']}",
                class_name="mt-2 text-[11px] text-zinc-400",
            ),
            rx.el.p(
                f"Source: {selection['source']} · Observed: {selection['observed']}",
                class_name="mt-2 text-[11px] text-zinc-400",
            ),
            rx.cond(
                selection["url"] != "",
                rx.el.a(
                    "Feed source",
                    href=selection["url"],
                    target="_blank",
                    rel="noopener noreferrer",
                    class_name="mt-2 inline-block text-xs text-zinc-300 underline decoration-[#EF233C] focus-visible:outline-2 focus-visible:outline-[#EF233C]",
                ),
            ),
            rx.cond(
                selection["chat"] != "",
                rx.el.a(
                    "View linked research context",
                    href=f"/selections?chat={selection['chat']}",
                    class_name="ml-3 mt-2 inline-block text-xs text-zinc-300 underline decoration-[#EF233C] focus-visible:outline-2 focus-visible:outline-[#EF233C]",
                ),
            ),
        ),
        rx.el.div(
            rx.el.button(
                "Use in calculator",
                on_click=SelectionsState.use_saved(selection["id"]),
                disabled=~selection["eligible"] | SelectionsState.saving,
                class_name=BUTTON,
            ),
            rx.el.a(
                "Manual transfer",
                href=f"/booking-codes?selection={selection['id']}",
                class_name=BUTTON,
            ),
            rx.el.button(
                "Edit",
                on_click=SelectionsState.edit_selection(selection["id"]),
                disabled=SelectionsState.saving,
                class_name=BUTTON,
            ),
            rx.el.button(
                rx.icon("trash-2", class_name="h-3.5 w-3.5"),
                "Remove",
                on_click=SelectionsState.remove_selection(selection["id"]),
                disabled=SelectionsState.saving,
                class_name=BUTTON,
            ),
            class_name="mt-4 flex flex-wrap gap-2",
        ),
        key=selection["id"],
        class_name="rounded-lg border border-white/10 bg-[#09090B] p-4",
    )


def selections_workspace() -> rx.Component:
    return rx.el.div(
        navigation(active="selections"),
        rx.el.main(
            rx.el.div(
                rx.el.div(
                    rx.el.p(
                        "PERSONALLY REVIEWED · NEVER AUTOMATICALLY PLACED",
                        class_name="text-[10px] font-semibold tracking-[0.14em] text-zinc-400",
                    ),
                    rx.el.h1(
                        "Selections & odds",
                        class_name="mt-2 text-2xl font-semibold tracking-tight text-[#F4F4F5] sm:text-3xl",
                    ),
                    rx.el.p(
                        "Compare exact market prices, keep your evidence, and set a cautious stake limit. No bet is a valid decision.",
                        class_name="mt-2 text-sm leading-6 text-zinc-400",
                    ),
                ),
                rx.el.a(
                    rx.icon("messages-square", class_name="h-4 w-4"),
                    "Return to research",
                    href="/",
                    class_name=BUTTON,
                ),
                class_name="mb-6 flex flex-wrap items-center justify-between gap-4",
            ),
            rx.cond(
                SelectionsState.loading,
                rx.el.div(
                    "Loading your private research & selections…",
                    role="status",
                    class_name="mb-4 animate-pulse rounded-lg border border-white/10 bg-[#141416] p-4 text-xs text-zinc-400",
                ),
            ),
            rx.cond(
                SelectionsState.error != "",
                rx.el.p(
                    SelectionsState.error,
                    role="alert",
                    class_name="mb-4 rounded-lg border border-red-400/20 bg-red-400/5 p-3 text-xs leading-5 text-red-300",
                ),
            ),
            rx.cond(
                SelectionsState.notice != "",
                rx.el.p(
                    SelectionsState.notice,
                    role="status",
                    class_name="mb-4 rounded-lg border border-white/10 bg-[#141416] p-3 text-xs text-zinc-300",
                ),
            ),
            rx.el.div(
                rx.el.div(
                    research_context(),
                    comparison(),
                    manual_form(),
                    class_name="min-w-0 space-y-4 lg:col-span-8",
                ),
                rx.el.div(
                    stake_calculator(),
                    connection_card(),
                    class_name="min-w-0 space-y-4 lg:col-span-4",
                ),
                class_name="grid w-full grid-cols-1 items-start gap-5 lg:grid-cols-12",
            ),
            rx.el.section(
                rx.el.div(
                    rx.el.h2(
                        "Your saved selections",
                        class_name="text-base font-semibold text-[#F4F4F5]",
                    ),
                    rx.el.span(
                        f"{SelectionsState.selections.length()} saved · private to your account",
                        class_name="text-xs text-zinc-400",
                    ),
                    class_name="mb-4 flex flex-wrap items-center justify-between gap-2",
                ),
                rx.cond(
                    SelectionsState.selections.length() > 0,
                    rx.el.div(
                        rx.foreach(SelectionsState.selections, saved_item),
                        class_name="grid gap-3 xl:grid-cols-2",
                    ),
                    rx.el.div(
                        rx.icon(
                            "bookmark", class_name="mb-3 h-5 w-5 text-zinc-500"
                        ),
                        rx.el.p(
                            "No saved selections yet",
                            class_name="text-sm text-zinc-300",
                        ),
                        rx.el.p(
                            "Save a personally reviewed price or a no-bet decision. Demo selections are never automatically saved.",
                            class_name="mt-2 text-xs text-zinc-400",
                        ),
                        class_name="rounded-lg border border-dashed border-white/15 p-6",
                    ),
                ),
                class_name="mt-6 w-full rounded-xl border border-white/10 bg-[#141416] p-4 sm:p-5",
            ),
            class_name="min-w-0 w-full flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8",
        ),
        class_name="flex h-dvh w-full flex-col overflow-hidden bg-[#09090B] font-['Inter'] text-[#F4F4F5]",
    )
