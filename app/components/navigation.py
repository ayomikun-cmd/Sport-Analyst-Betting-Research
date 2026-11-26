import reflex as rx

from reflex_enterprise.auth import User
from app.states.research_state import ResearchState


def brand() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.icon("goal", class_name="h-5 w-5 text-white"),
            class_name="flex h-9 w-9 items-center justify-center rounded-xl bg-[#EF233C]",
        ),
        rx.el.span(
            "Sport Analyst",
            class_name="text-lg font-semibold tracking-tight text-[#F4F4F5]",
        ),
        class_name="flex shrink-0 items-center gap-3",
    )


def navigation(active: str = "research") -> rx.Component:
    return rx.el.header(
        rx.el.div(
            brand(), class_name="col-start-1 row-start-1 flex items-center"
        ),
        rx.el.nav(
            rx.el.a(
                rx.icon("messages-square", class_name="h-4 w-4"),
                "Research",
                href="/",
                aria_current=rx.cond(active == "research", "page", "false"),
                class_name=rx.cond(
                    active == "research",
                    "flex items-center gap-2 border-b-2 border-[#EF233C] px-3 py-4 text-sm font-medium text-[#F4F4F5] focus-visible:outline-2 focus-visible:outline-[#EF233C]",
                    "flex items-center gap-2 border-b-2 border-transparent px-3 py-4 text-sm font-medium text-zinc-400 hover:text-[#F4F4F5] focus-visible:outline-2 focus-visible:outline-[#EF233C]",
                ),
            ),
            rx.el.a(
                "Selections",
                href="/selections",
                aria_current=rx.cond(active == "selections", "page", "false"),
                class_name=rx.cond(
                    active == "selections",
                    "border-b-2 border-[#EF233C] px-3 py-4 text-sm font-medium text-[#F4F4F5] focus-visible:outline-2 focus-visible:outline-[#EF233C]",
                    "border-b-2 border-transparent px-3 py-4 text-sm text-zinc-400 hover:text-[#F4F4F5] focus-visible:outline-2 focus-visible:outline-[#EF233C]",
                ),
            ),
            rx.el.button(
                "Booking Codes",
                disabled=True,
                title="Available in a later phase",
                class_name="cursor-not-allowed px-3 py-4 text-sm text-zinc-400",
            ),
            aria_label="Main navigation",
            class_name="col-span-2 row-start-2 flex items-center justify-center gap-1 md:col-span-1 md:col-start-2 md:row-start-1 md:gap-5",
        ),
        rx.el.button(
            rx.icon("log-out", class_name="h-4 w-4"),
            rx.el.span("Log out", class_name="hidden sm:inline"),
            on_click=User.logout,
            aria_label="Log out",
            class_name="col-start-2 row-start-1 flex items-center justify-self-end gap-2 rounded-lg p-2 text-sm text-zinc-300 hover:bg-white/5 focus-visible:outline-2 focus-visible:outline-[#EF233C] md:col-start-3",
        ),
        class_name="grid shrink-0 grid-cols-[1fr_auto] items-center border-b border-white/10 bg-[#09090B] px-4 pt-4 md:h-[76px] md:grid-cols-[1fr_auto_1fr] md:px-8 md:pt-0",
    )


def research_toolbar() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.button(
                rx.icon("panel-left", class_name="h-4 w-4"),
                on_click=ResearchState.toggle_history,
                aria_label="Toggle saved research",
                aria_expanded=ResearchState.history_open,
                aria_controls="research-history",
                class_name="rounded-lg p-2 text-zinc-300 hover:bg-white/5 focus-visible:outline-2 focus-visible:outline-[#EF233C] md:hidden",
            ),
            rx.el.span(
                "FOOTBALL RESEARCH",
                class_name="text-[11px] font-semibold tracking-[0.16em] text-zinc-400",
            ),
            class_name="flex items-center gap-2",
        ),
        rx.el.div(
            rx.el.span(
                rx.icon("circle", class_name="h-2 w-2 fill-current"),
                rx.cond(
                    ResearchState.sample_mode,
                    "Sample mode",
                    "Live ready · not yet verified",
                ),
                class_name="hidden items-center gap-2 text-xs text-zinc-400 sm:flex",
            ),
            rx.el.button(
                rx.icon("plus", class_name="h-4 w-4"),
                "New research",
                on_click=ResearchState.new_research,
                disabled=ResearchState.busy,
                class_name="flex items-center gap-2 rounded-lg border border-white/15 bg-[#141416] px-3 py-2 text-xs font-medium text-[#F4F4F5] hover:border-white/30 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-[#EF233C]",
            ),
            class_name="flex items-center gap-4",
        ),
        class_name="flex h-16 shrink-0 items-center justify-between border-b border-white/10 px-4 md:px-7",
    )
