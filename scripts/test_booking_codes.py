import reflex as rx

import asyncio
from datetime import datetime, timedelta, timezone

from test_utils import run_event
from app.states.booking_codes_state import BookingCodesState


async def main():
    state = BookingCodesState()
    assert isinstance(state, rx.State)
    await run_event(state.check_conversion)
    assert "Enter an existing" in state.error and not state.legs
    await run_event(state.set_code, "x" * 257)
    await run_event(state.check_conversion)
    assert "256" in state.error and not state.legs
    await run_event(state.set_code, "PERSONALLY-SUPPLIED-CODE")
    await run_event(state.check_conversion)
    assert (
        state.conversion_notice
        == "Code cannot be resolved or converted: no verified operator integration. Load the slip in its source bookmaker and enter/import the selections below."
    )
    assert not state.legs and not state.output
    await run_event(state.native_code)
    assert "unavailable" in state.conversion_notice and not state.output

    now = datetime.now(timezone.utc)
    details = {
        "home": "Personal home fixture",
        "away": "Personal away fixture",
        "competition": "Personally entered competition",
        "category": "Senior men",
        "kickoff": (now + timedelta(days=2)).isoformat(),
        "market": "Match result",
        "outcome": "Home",
        "line": "",
        "period": "90 minutes",
        "subject": "",
        "cards": "Not applicable — non-card market",
        "rules": "Personally reviewed: 90 minutes only, excludes extra time",
        "bookmaker": "SportyBet",
        "price": "",
        "observed": "",
        "destination_price": "2.10",
        "destination_observed": now.isoformat(),
        "evidence": "Personal destination UI review notes",
        "rationale": "Personal research gaps recorded",
    }
    await run_event(state.save_leg, details)
    assert not state.error and len(state.legs) == 1
    identity = state.legs[0]["id"]
    await run_event(state.prepare_manual_transfer)
    assert "Manual transfer — NOT a bookmaker booking code" in state.output
    assert "Unresolved: 1" in state.output and not state.total_odds
    await run_event(state.review_leg, identity, {"event": True, "market": True})
    assert not state.error and state.legs[0]["event_reviewed"]
    await run_event(state.prepare_manual_transfer)
    assert state.total_odds == "2.1" and "MANUAL / UNVERIFIED" in state.output
    await run_event(state.save_leg, details)
    assert (
        "already" in state.error and len(state.legs) == 1 and not state.output
    )

    await run_event(state.edit_leg, identity)
    await run_event(
        state.save_leg,
        {**details, "market": "Total goals", "outcome": "Over", "line": "2.5"},
    )
    assert state.legs[0]["changed"] and not state.legs[0]["event_reviewed"]
    assert state.legs[0]["original"]["market"] == "Match result"
    await run_event(state.revert_leg, identity)
    assert (
        not state.legs[0]["changed"]
        and state.legs[0]["details"]["market"] == "Match result"
    )
    assert not state.legs[0]["details"]["destination_price"]
    await run_event(state.mark_missing, identity)
    await run_event(state.prepare_manual_transfer)
    assert "explicitly exclude" in state.error and not state.output
    await run_event(
        state.set_inclusion, identity, {"reason": "Missing destination market"}
    )
    assert not state.legs[0]["included"]
    await run_event(state.set_inclusion, identity, {})
    assert state.legs[0]["included"] and not state.legs[0]["event_reviewed"]

    await run_event(state.edit_leg, identity)
    await run_event(state.save_leg, details)
    await run_event(state.review_leg, identity, {"event": True, "market": True})
    await run_event(state.prepare_manual_transfer)
    assert state.output
    await run_event(state.set_bookmaker, "destination", "BetKing")
    assert not state.output and not state.legs[0]["event_reviewed"]
    assert not state.legs[0]["details"]["destination_price"]

    await run_event(state.edit_leg, identity)
    await run_event(state.save_leg, {**details, "destination_price": "NaN"})
    assert "finite" in state.error and not state.output
    await run_event(state.save_leg, {**details, "kickoff": ""})
    await run_event(state.prepare_manual_transfer)
    assert "unknown kickoff" in state.error
    await run_event(state.edit_leg, identity)
    await run_event(
        state.save_leg,
        {**details, "kickoff": (now - timedelta(days=1)).isoformat()},
    )
    await run_event(state.prepare_manual_transfer)
    assert "started/settled" in state.error and state.legs[0]["included"]
    await run_event(
        state.set_inclusion,
        identity,
        {"reason": "Fixture started; prematch blocked"},
    )
    await run_event(
        state.save_leg,
        {
            **details,
            "home": "Another personal home fixture",
            "away": "Another personal away fixture",
        },
    )
    assert len(state.legs) == 2
    second = state.legs[1]["id"]
    await run_event(state.review_leg, second, {"event": True, "market": True})
    await run_event(state.prepare_manual_transfer)
    assert (
        "EXCLUDED" in state.output
        and "Fixture started; prematch blocked" in state.output
    )
    assert state.total_odds == "2.1"

    await run_event(
        state.save_leg,
        {
            **details,
            "home": "Another personal home fixture",
            "away": "Another personal away fixture",
            "market": "Total goals",
            "outcome": "Over",
            "line": "2.5",
        },
    )
    third = state.legs[2]["id"]
    await run_event(state.review_leg, third, {"event": True, "market": True})
    await run_event(state.prepare_manual_transfer)
    assert "correlated" in state.output and not state.total_odds
    await run_event(state.edit_leg, second)
    await run_event(
        state.save_leg,
        {
            **details,
            "home": "Another personal home fixture",
            "away": "Another personal away fixture",
            "destination_observed": (now - timedelta(minutes=11)).isoformat(),
        },
    )
    await run_event(state.review_leg, second, {"event": True, "market": True})
    await run_event(state.prepare_manual_transfer)
    assert "unknown / stale" in state.output and not state.total_odds
    await run_event(state.remove_leg, third)
    assert not state.output and len(state.legs) == 2
    print(
        "Booking-code unsupported handling and transient manual transfer event checks passed. No database writes, operator calls, authentication simulation or fabricated codes."
    )


if __name__ == "__main__":
    asyncio.run(main())
