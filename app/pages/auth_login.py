import reflex as rx

import os
from collections.abc import Sequence

from reflex_enterprise.auth import AuthUserState
from reflex_enterprise.auth.types import AuthProvider
from app.states.login_redirect_state import LoginRedirectState
from app.components.navigation import brand

_PROVIDER_NAME = os.environ.get("OIDC_PROVIDER_NAME", "")
_LOGIN_LABEL = (
    f"Continue with {_PROVIDER_NAME}" if _PROVIDER_NAME else "Sign in"
)


def _provider_buttons(
    providers: Sequence[type[AuthProvider]],
) -> list[rx.Component]:
    return [
        provider.get_login_button(
            rx.el.button(
                _LOGIN_LABEL,
                class_name="w-full rounded-lg bg-[#EF233C] px-5 py-3 text-sm font-semibold text-white transition-colors hover:bg-[#D91F36] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#EF233C]",
            )
        )
        for provider in providers
    ]


def login_page(*, providers: Sequence, **context) -> rx.Component:
    return rx.fragment(
        rx.el.main(
            rx.el.section(
                rx.el.div(brand(), class_name="mb-10"),
                rx.el.h1(
                    "Sign in",
                    class_name="mb-3 text-3xl font-semibold tracking-tight text-[#F4F4F5]",
                ),
                rx.el.p(
                    "Access your private football research conversations.",
                    class_name="mb-8 text-sm leading-6 text-zinc-400",
                ),
                *_provider_buttons(providers),
                rx.el.div(
                    rx.icon("lock-keyhole", class_name="h-3 w-3"),
                    "Research is private to your account",
                    class_name="mt-6 flex items-center justify-center gap-2 text-xs text-zinc-400",
                ),
                class_name="w-full max-w-sm rounded-2xl border border-white/10 bg-[#141416] p-8",
            ),
            class_name="flex min-h-dvh items-center justify-center bg-[#09090B] px-6 py-12 font-['Inter'] text-white",
        ),
        rx.cond(
            AuthUserState.provider_name != "",
            rx.el.div(on_mount=LoginRedirectState.continue_to_app),
        ),
    )
