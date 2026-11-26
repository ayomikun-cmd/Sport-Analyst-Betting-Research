import reflex as rx
import reflex_enterprise as rxe
from reflex.model import ModelRegistry

from app.models import Base
from app.components.research_workspace import research_workspace
from app.states.research_state import ResearchState
from app.states.selections_state import SelectionsState
from app.pages.selections import selections_page

ModelRegistry.register(Base)


@rxe.page(auth=True)
def index() -> rx.Component:
    return research_workspace()


app = rxe.App(
    head_components=[
        rx.el.link(rel="preconnect", href="https://fonts.googleapis.com"),
        rx.el.link(
            rel="preconnect",
            href="https://fonts.gstatic.com",
            cross_origin="",
        ),
        rx.el.link(
            href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap",
            rel="stylesheet",
        ),
    ],
)
app.add_page(
    index,
    route="/",
    title="Sport Analyst · Football Research",
    on_load=ResearchState.load,
)
app.add_page(
    selections_page,
    route="/selections",
    title="Sport Analyst · Selections & Odds",
    on_load=SelectionsState.load,
)
