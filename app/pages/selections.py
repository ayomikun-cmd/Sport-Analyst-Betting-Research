import reflex as rx
import reflex_enterprise as rxe

from app.components.selections_workspace import selections_workspace


@rxe.page(auth=True)
def selections_page() -> rx.Component:
    return selections_workspace()
