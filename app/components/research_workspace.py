import reflex as rx

from app.components.navigation import navigation, research_toolbar
from app.research_service import ChatView, MessageView, Source
from app.states.research_state import ResearchState


PROMPTS = [
    {
        "title": "Head-to-head",
        "description": "Dated meetings & match context",
        "icon": "swords",
        "prompt": "Compare recent head-to-head results for [home] vs [away], [competition], [date], [senior men / women / youth].",
    },
    {
        "title": "Current form",
        "description": "Last five competitive results",
        "icon": "chart-no-axes-combined",
        "prompt": "Research the last five competitive results for [home] and [away] before their [competition] fixture on [date]. Confirm the team category.",
    },
    {
        "title": "Squad availability",
        "description": "Confirmed absences vs reports",
        "icon": "users",
        "prompt": "Check confirmed absences and uncertain squad reports for [home] vs [away], [competition], [date], [team category].",
    },
    {
        "title": "Referee & cards",
        "description": "Appointments, history & evidence gaps",
        "icon": "flag",
        "prompt": "Research the official referee appointment and sourced card history for [home] vs [away], [competition], [date], [team category]. Explain bookings settlement gaps and the no-bet option.",
    },
]


def connection_notice() -> rx.Component:
    return rx.el.div(
        rx.icon("info", class_name="h-4 w-4 shrink-0 text-[#EF233C]"),
        rx.el.div(
            rx.el.p(
                rx.cond(
                    ResearchState.sample_mode,
                    "Sample research — connect OpenAI for live analysis",
                    "Live research enabled — evidence is checked per request",
                ),
                class_name="text-xs font-medium text-[#F4F4F5]",
            ),
            rx.el.p(
                rx.cond(
                    ResearchState.sample_mode,
                    "Fictional demonstration only. No live analysis of your fixture.",
                    "Web-search citations are AI-retrieved, not independently verified. Review dates and gaps.",
                ),
                class_name="mt-1 text-xs leading-relaxed text-zinc-400",
            ),
        ),
        class_name="flex items-start gap-3 rounded-xl border border-white/10 bg-[#141416] px-4 py-3",
    )


def history_item(chat: ChatView) -> rx.Component:
    return rx.el.button(
        rx.el.div(
            rx.icon(
                "message-square",
                class_name="mt-0.5 h-4 w-4 shrink-0 text-zinc-400",
            ),
            rx.el.span(
                chat["title"],
                class_name="line-clamp-2 text-left text-sm leading-5",
            ),
            class_name="flex items-start gap-2",
        ),
        rx.el.p(
            chat["updated"],
            class_name="mt-2 pl-6 text-left text-[11px] text-zinc-400",
        ),
        on_click=ResearchState.open_chat(chat["id"]),
        disabled=ResearchState.busy,
        key=chat["id"],
        class_name=rx.cond(
            ResearchState.active_chat == chat["id"],
            "w-full rounded-lg border border-white/10 bg-white/5 p-3 text-[#F4F4F5] disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-[#EF233C]",
            "w-full rounded-lg border border-transparent bg-transparent p-3 text-zinc-300 hover:bg-white/5 disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-[#EF233C]",
        ),
    )


def history_rail() -> rx.Component:
    return rx.el.aside(
        rx.el.div(
            rx.el.h2(
                "Your research",
                class_name="text-sm font-semibold text-[#F4F4F5]",
            ),
            rx.el.p(
                "Private, saved conversations",
                class_name="mt-1 text-xs text-zinc-400",
            ),
            class_name="shrink-0 px-5 pb-4 pt-6",
        ),
        rx.el.nav(
            rx.cond(
                ResearchState.chats.length() > 0,
                rx.foreach(ResearchState.chats, history_item),
                rx.el.div(
                    rx.icon(
                        "messages-square",
                        class_name="mb-3 h-5 w-5 text-zinc-500",
                    ),
                    rx.el.p(
                        "No saved research yet",
                        class_name="text-xs text-zinc-300",
                    ),
                    rx.el.p(
                        "Your first question starts a conversation.",
                        class_name="mt-2 text-xs leading-5 text-zinc-400",
                    ),
                    class_name="rounded-xl border border-dashed border-white/10 p-4",
                ),
            ),
            aria_label="Saved research conversations",
            class_name="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-3 pb-4",
        ),
        rx.el.div(
            rx.icon("lock-keyhole", class_name="h-3 w-3"),
            "Only visible to your account",
            class_name="flex shrink-0 items-center gap-2 border-t border-white/10 p-5 text-[11px] text-zinc-400",
        ),
        id="research-history",
        class_name=rx.cond(
            ResearchState.history_open,
            "absolute inset-y-0 left-0 z-20 flex w-[240px] shrink-0 flex-col border-r border-white/10 bg-[#101012] md:static",
            "hidden w-[240px] shrink-0 flex-col border-r border-white/10 bg-[#101012] md:flex",
        ),
    )


def prompt_card(item: dict[str, str]) -> rx.Component:
    return rx.el.button(
        rx.icon(item["icon"], class_name="mb-4 h-5 w-5 text-[#EF233C]"),
        rx.el.div(
            rx.el.span(
                item["title"], class_name="text-sm font-medium text-[#F4F4F5]"
            ),
            rx.icon("arrow-up-right", class_name="h-4 w-4 text-zinc-500"),
            class_name="flex items-center justify-between",
        ),
        rx.el.p(
            item["description"],
            class_name="mt-2 text-xs leading-5 text-zinc-400",
        ),
        on_click=ResearchState.choose_prompt(item["prompt"]),
        disabled=ResearchState.busy,
        class_name="rounded-xl border border-white/10 bg-[#141416] p-5 text-left transition-colors hover:border-white/25 hover:bg-[#1A1A1D] disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-[#EF233C]",
    )


def welcome() -> rx.Component:
    return rx.el.section(
        rx.el.div(
            rx.el.div(
                rx.el.div(
                    class_name="absolute inset-y-0 left-1/2 border-l border-white/15"
                ),
                rx.el.div(
                    class_name="absolute left-1/2 top-1/2 h-9 w-9 -translate-x-1/2 -translate-y-1/2 rounded-full border border-white/15"
                ),
                rx.el.div(
                    class_name="absolute left-0 top-1/2 h-10 w-5 -translate-y-1/2 border-y border-r border-white/15"
                ),
                rx.el.div(
                    class_name="absolute right-0 top-1/2 h-10 w-5 -translate-y-1/2 border-y border-l border-white/15"
                ),
                rx.icon(
                    "goal",
                    class_name="absolute -bottom-3 -right-3 h-9 w-9 rounded-lg bg-[#09090B] p-1.5 text-[#EF233C]",
                ),
                aria_hidden=True,
                class_name="relative mb-9 h-20 w-36 rounded-lg border border-white/15 bg-transparent",
            ),
            rx.el.p(
                "MATCH RESEARCH",
                class_name="mb-3 text-[10px] font-semibold tracking-[0.2em] text-zinc-400",
            ),
            rx.el.h1(
                "Sport Analyst",
                class_name="text-3xl font-semibold tracking-tight text-[#F4F4F5] sm:text-4xl",
            ),
            rx.el.p(
                "What would you like to know about the match?",
                class_name="mt-4 text-base text-zinc-300",
            ),
            rx.el.p(
                "Include both teams, fixture date, competition and team category. Start with a question below or write your own.",
                class_name="mt-3 max-w-xl text-sm leading-6 text-zinc-400",
            ),
            class_name="flex flex-col items-center text-center",
        ),
        rx.el.div(
            rx.foreach(PROMPTS, prompt_card),
            class_name="mt-9 grid w-full grid-cols-1 gap-3 sm:grid-cols-2",
        ),
        class_name="mx-auto flex w-full max-w-[760px] flex-col px-4 py-9 sm:px-8 lg:py-14",
    )


def safe_markdown_link(*children, **props) -> rx.Component:
    return rx.cond(
        props.get("href", "").lower().startswith("https://")
        | props.get("href", "").lower().startswith("http://"),
        rx.el.a(
            *children,
            href=props.get("href", ""),
            target="_blank",
            rel="noopener noreferrer",
            class_name="text-[#F4F4F5] underline decoration-[#EF233C] underline-offset-4 hover:text-white focus-visible:outline-2 focus-visible:outline-[#EF233C]",
        ),
        rx.el.span(*children, class_name="text-zinc-300"),
    )


def source_link(source: Source) -> rx.Component:
    return rx.el.a(
        rx.icon(
            "external-link", class_name="mt-0.5 h-3 w-3 shrink-0 text-zinc-400"
        ),
        rx.el.div(
            rx.el.p(
                source["title"], class_name="text-xs font-medium text-zinc-200"
            ),
            rx.el.p(
                rx.cond(
                    source["kind"] == "citation",
                    "Cited in report",
                    "Consulted by web search",
                ),
                class_name="mt-1 text-[10px] text-zinc-400",
            ),
        ),
        href=source["url"],
        target="_blank",
        rel="noopener noreferrer",
        key=source["url"],
        class_name="flex items-start gap-2 rounded-lg border border-white/10 bg-[#141416] px-3 py-2 hover:border-white/25 focus-visible:outline-2 focus-visible:outline-[#EF233C]",
    )


def evidence_panel(message: MessageView) -> rx.Component:
    return rx.el.details(
        rx.el.summary(
            rx.icon("book-open-check", class_name="h-4 w-4 text-zinc-400"),
            rx.cond(
                message["status"] == "sample",
                "Evidence & sources · unavailable in sample",
                "Sources, research time & evidence gaps",
            ),
            class_name="flex cursor-pointer items-center gap-2 text-xs font-medium text-zinc-300 focus-visible:outline-2 focus-visible:outline-[#EF233C]",
        ),
        rx.el.div(
            rx.cond(
                message["status"] == "sample",
                rx.el.p(
                    "Fictional demonstration. No sources retrieved and no freshness claim.",
                    class_name="text-xs leading-5 text-zinc-400",
                ),
                rx.el.div(
                    rx.el.p(
                        f"Researched at: {message['researched_at']}",
                        class_name="text-xs text-zinc-300",
                    ),
                    rx.el.p(
                        "This timestamp does not confirm all sources are fresh. Check publication dates in the report. Citations are not independent verification.",
                        class_name="mt-2 text-xs leading-5 text-zinc-400",
                    ),
                ),
            ),
            rx.cond(
                message["sources"].length() > 0,
                rx.el.div(
                    rx.foreach(message["sources"], source_link),
                    class_name="mt-4 grid gap-2 sm:grid-cols-2",
                ),
                rx.el.p(
                    "No substantiating source links available.",
                    class_name="mt-3 text-xs text-zinc-400",
                ),
            ),
            rx.el.h3(
                "Evidence gaps",
                class_name="mb-2 mt-4 text-xs font-semibold text-[#F4F4F5]",
            ),
            rx.el.ul(
                rx.foreach(
                    message["gaps"],
                    lambda gap: rx.el.li(
                        gap, class_name="text-xs leading-5 text-zinc-400"
                    ),
                ),
                class_name="list-disc space-y-1 pl-4",
            ),
            class_name="pt-4",
        ),
        open=True,
        class_name="mt-5 rounded-xl border border-white/10 bg-[#101012] p-4",
    )


def message_card(message: MessageView) -> rx.Component:
    return rx.el.article(
        rx.el.div(
            rx.icon(
                rx.cond(message["role"] == "user", "user-round", "goal"),
                class_name="h-4 w-4 text-zinc-300",
            ),
            rx.el.span(
                rx.cond(message["role"] == "user", "You", "Sport Analyst"),
                class_name="text-xs font-semibold text-[#F4F4F5]",
            ),
            rx.el.span(
                rx.cond(
                    message["role"] == "user",
                    "Unverified user context",
                    rx.cond(
                        message["status"] == "sample",
                        "SAMPLE · NO LIVE ANALYSIS",
                        "WEB RESEARCH · REVIEW EVIDENCE",
                    ),
                ),
                class_name="ml-auto text-[9px] font-medium tracking-wide text-zinc-400",
            ),
            class_name="mb-4 flex flex-wrap items-center gap-2",
        ),
        rx.cond(
            message["role"] == "user",
            rx.el.p(
                message["content"],
                class_name="whitespace-pre-wrap break-words text-sm leading-7 text-zinc-200",
            ),
            rx.el.div(
                rx.markdown(
                    message["content"],
                    component_map={
                        "a": safe_markdown_link,
                        "img": lambda *children, **props: rx.el.span(
                            "[Image omitted]", class_name="text-zinc-400"
                        ),
                    },
                ),
                evidence_panel(message),
                class_name="text-sm leading-7 text-zinc-200 [&_h1]:mb-4 [&_h1]:text-2xl [&_h1]:font-semibold [&_h1]:text-[#F4F4F5] [&_h2]:mb-3 [&_h2]:mt-6 [&_h2]:text-lg [&_h2]:font-semibold [&_h2]:text-[#F4F4F5] [&_h3]:mb-2 [&_h3]:mt-5 [&_h3]:font-semibold [&_h3]:text-[#F4F4F5] [&_p]:mb-3 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5 [&_strong]:text-[#F4F4F5] [&_table]:block [&_table]:w-full [&_table]:overflow-x-auto [&_table]:text-xs [&_td]:border-b [&_td]:border-white/10 [&_td]:p-2 [&_th]:p-2 [&_th]:text-left",
            ),
        ),
        key=message["id"],
        class_name=rx.cond(
            message["role"] == "user",
            "rounded-xl border border-white/10 bg-[#141416] p-5",
            "border-b border-white/10 bg-transparent px-1 py-5",
        ),
    )


def composer() -> rx.Component:
    return rx.el.div(
        rx.el.form(
            rx.el.div(
                rx.el.label(
                    "Ask about a football match",
                    html_for="research-prompt",
                    class_name="text-xs font-medium text-zinc-300",
                ),
                rx.el.div(
                    rx.el.button(
                        "Sample",
                        type="button",
                        on_click=ResearchState.set_sample_mode(True),
                        disabled=ResearchState.busy,
                        class_name=rx.cond(
                            ResearchState.sample_mode,
                            "rounded-md bg-white/10 px-2 py-1 text-[10px] text-white focus-visible:outline-2 focus-visible:outline-[#EF233C]",
                            "rounded-md bg-transparent px-2 py-1 text-[10px] text-zinc-400 focus-visible:outline-2 focus-visible:outline-[#EF233C]",
                        ),
                    ),
                    rx.el.button(
                        "Live",
                        type="button",
                        on_click=ResearchState.set_sample_mode(False),
                        disabled=ResearchState.busy
                        | ~ResearchState.live_available,
                        title="Live mode requires OpenAI service access",
                        class_name=rx.cond(
                            ResearchState.sample_mode,
                            "rounded-md bg-transparent px-2 py-1 text-[10px] text-zinc-400 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-[#EF233C]",
                            "rounded-md bg-white/10 px-2 py-1 text-[10px] text-white focus-visible:outline-2 focus-visible:outline-[#EF233C]",
                        ),
                    ),
                    class_name="flex rounded-lg border border-white/10 bg-[#09090B] p-1",
                ),
                class_name="mb-3 flex items-center justify-between",
            ),
            rx.el.div(
                rx.el.input(
                    id="research-prompt",
                    name="prompt",
                    default_value=ResearchState.draft,
                    key=ResearchState.draft,
                    placeholder="Teams, date, competition… or add unverified context",
                    max_length=3000,
                    required=True,
                    disabled=ResearchState.busy,
                    aria_describedby="composer-help",
                    class_name="min-w-0 flex-1 rounded-xl border border-white/15 bg-[#09090B] px-4 py-3 text-sm text-[#F4F4F5] placeholder:text-zinc-500 focus:border-[#EF233C] focus:outline-hidden disabled:opacity-60",
                ),
                rx.el.button(
                    rx.cond(
                        ResearchState.researching,
                        rx.icon(
                            "loader-circle", class_name="h-4 w-4 animate-spin"
                        ),
                        rx.icon("arrow-up", class_name="h-4 w-4"),
                    ),
                    rx.el.span(
                        rx.cond(
                            ResearchState.sample_mode,
                            "Sample research",
                            "Research",
                        ),
                        class_name="hidden sm:inline",
                    ),
                    type="submit",
                    disabled=ResearchState.busy,
                    aria_label="Submit research prompt",
                    class_name="flex shrink-0 items-center gap-2 rounded-xl bg-[#EF233C] px-4 py-3 text-sm font-semibold text-white hover:bg-[#D91F36] disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#EF233C]",
                ),
                class_name="flex gap-2",
            ),
            on_submit=ResearchState.submit,
            class_name="w-full",
        ),
        rx.cond(
            ResearchState.error != "",
            rx.el.p(
                ResearchState.error,
                role="alert",
                class_name="mt-3 text-xs leading-5 text-red-300",
            ),
        ),
        rx.el.div(
            rx.el.p(
                "3,000 characters max · 18+ · No guaranteed picks. Never risk money you cannot afford to lose.",
                id="composer-help",
                class_name="text-[10px] leading-4 text-zinc-400",
            ),
            rx.cond(
                ResearchState.researching,
                rx.el.button(
                    rx.cond(
                        ResearchState.cancel_requested, "Stopping…", "Cancel"
                    ),
                    on_click=ResearchState.cancel_research,
                    disabled=ResearchState.cancel_requested,
                    class_name="shrink-0 rounded px-2 py-1 text-xs text-zinc-300 hover:bg-white/5 focus-visible:outline-2 focus-visible:outline-[#EF233C]",
                ),
            ),
            class_name="mt-3 flex items-center justify-between gap-3",
        ),
        class_name="shrink-0 border-t border-white/10 bg-[#141416] px-4 py-4 md:px-8",
    )


def research_workspace() -> rx.Component:
    return rx.el.div(
        navigation(),
        research_toolbar(),
        rx.el.div(
            rx.cond(
                ResearchState.history_open,
                rx.el.button(
                    on_click=ResearchState.toggle_history,
                    aria_label="Close research history",
                    class_name="absolute inset-0 z-10 bg-black/60 md:hidden",
                ),
            ),
            history_rail(),
            rx.el.main(
                rx.el.div(
                    connection_notice(), class_name="shrink-0 px-4 pt-4 md:px-8"
                ),
                rx.el.div(
                    rx.cond(
                        ResearchState.messages.length() == 0,
                        welcome(),
                        rx.el.div(
                            rx.foreach(ResearchState.messages, message_card),
                            class_name="mx-auto flex w-full max-w-[960px] flex-col gap-5 px-4 py-7 md:px-8",
                        ),
                    ),
                    rx.cond(
                        ResearchState.researching,
                        rx.el.div(
                            rx.icon(
                                "loader-circle",
                                class_name="h-4 w-4 animate-spin text-[#EF233C]",
                            ),
                            rx.cond(
                                ResearchState.sample_mode,
                                "Preparing fictional sample…",
                                "Researching dated evidence and source gaps…",
                            ),
                            role="status",
                            class_name="mx-auto flex w-full max-w-[960px] items-center gap-3 px-6 pb-7 text-xs text-zinc-400",
                        ),
                    ),
                    rx.el.div(id="thread-end"),
                    aria_label="Research conversation",
                    aria_busy=ResearchState.researching,
                    class_name="min-h-0 flex-1 overflow-y-auto overscroll-contain",
                ),
                rx.cond(
                    ResearchState.active_chat != "",
                    rx.el.div(
                        rx.el.a(
                            rx.icon("bookmark-plus", class_name="h-3.5 w-3.5"),
                            "Review selections & odds with this research",
                            href=f"/selections?chat={ResearchState.active_chat}",
                            class_name="inline-flex items-center gap-2 rounded-lg px-2 py-2 text-xs text-zinc-300 hover:bg-white/5 focus-visible:outline-2 focus-visible:outline-[#EF233C]",
                        ),
                        class_name="shrink-0 border-t border-white/10 px-4 md:px-8",
                    ),
                ),
                composer(),
                class_name="flex min-h-0 min-w-0 w-full flex-1 flex-col bg-[#09090B]",
            ),
            class_name="relative flex min-h-0 flex-1",
        ),
        class_name="flex h-dvh w-full flex-col overflow-hidden bg-[#09090B] font-['Inter'] text-[#F4F4F5]",
    )
