import reflex as rx
import reflex_enterprise as rxe

from app.components.booking_codes_workspace import booking_codes_workspace


@rxe.page(auth=True)
def booking_codes_page() -> rx.Component:
    return booking_codes_workspace()
