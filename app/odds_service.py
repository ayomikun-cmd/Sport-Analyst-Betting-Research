import reflex as rx

import os
import json
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import TypedDict
from urllib.parse import parse_qsl, urlsplit

import httpx

from app.models import SavedSelection
from app.research_service import safe_url

BOOKMAKERS = ["SportyBet", "Bet9ja", "BetKing"]
BASE = "https://api.odds-api.io/v3"


class OddsUnavailable(RuntimeError):
    pass


class FixtureView(TypedDict):
    id: str
    home: str
    away: str
    competition: str
    kickoff: str
    status: str
    replacement: str


class QuoteView(TypedDict):
    id: str
    event_id: str
    home: str
    away: str
    competition: str
    kickoff: str
    bookmaker: str
    market: str
    outcome: str
    line: str
    period: str
    subject: str
    cards: str
    rules: str
    price: str
    observed: str
    freshness: str
    status: str
    supported: bool
    eligible: bool
    highest: bool
    source: str
    url: str
    raw: str
    note: str


class SelectionView(TypedDict):
    id: str
    chat: str
    home: str
    away: str
    competition: str
    kickoff: str
    market: str
    outcome: str
    line: str
    period: str
    subject: str
    cards: str
    rules: str
    bookmaker: str
    price: str
    observed: str
    status: str
    rationale: str
    source: str
    url: str
    event_id: str
    freshness: str
    eligible: bool


def available() -> bool:
    return bool(os.environ.get("ODDS_API_IO_KEY", "").strip())


def timestamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise ValueError(
            "Enter a valid timestamp with timezone, for example 2026-08-01T15:00:00Z."
        ) from None


def utc_input(value: str) -> datetime:
    return timestamp(
        f"{value}Z"
        if value and not value.endswith("Z") and len(value) in {16, 19}
        else value
    )


def decimal_price(value: str) -> Decimal:
    try:
        result = Decimal(str(value))
        if (
            not result.is_finite()
            or result <= 1
            or result >= Decimal("1000000000000")
        ):
            raise ValueError
        if result.as_tuple().exponent < -6:
            raise ValueError
        return result
    except (InvalidOperation, ValueError):
        raise ValueError(
            "Decimal odds must be finite, greater than 1, with at most 6 decimal places."
        ) from None


def https_source(value: str) -> str:
    cleaned = safe_url(value)
    if not cleaned or urlsplit(cleaned).scheme.lower() != "https":
        return ""
    if any(
        key.lower() in {"apikey", "api_key", "token", "key", "access_token"}
        for key, _ in parse_qsl(urlsplit(cleaned).query)
    ):
        return ""
    return cleaned


def freshness(observed: str, *, sample: bool = False) -> tuple[str, bool]:
    if sample:
        return "Fixed sample timestamp · not live", True
    try:
        age = (datetime.now(timezone.utc) - timestamp(observed)).total_seconds()
    except ValueError:
        return "Feed timestamp unavailable · unverified", False
    if age < -60:
        return "Future timestamp · unverified", False
    minutes = max(0, int(age // 60))
    return (
        f"{minutes} min old · stale" if age > 600 else f"{minutes} min old"
    ), age <= 600


def prematch(fixture: FixtureView) -> None:
    if fixture["replacement"]:
        raise OddsUnavailable(
            f"Fixture replaced by event {fixture['replacement']}. Search and explicitly select the replacement; it is not automatically substituted."
        )
    if fixture["status"] != "pending":
        raise OddsUnavailable(
            f"Fixture status is {fixture['status'] or 'unknown'}. Only pending pre-match fixtures are supported; select another fixture."
        )
    try:
        if timestamp(fixture["kickoff"]) <= datetime.now(timezone.utc):
            raise OddsUnavailable(
                "Kickoff has passed. In-play or settled selections are not supported for pre-match calculations."
            )
    except ValueError:
        raise OddsUnavailable(
            "Fixture kickoff is missing or invalid. Select a fixture with a confirmed kickoff."
        ) from None


def fixture_view(row: dict) -> FixtureView:
    league = row.get("league") or {}
    return {
        "id": str(row.get("id", "")),
        "home": str(row.get("home", "")),
        "away": str(row.get("away", "")),
        "competition": str(league.get("name", ""))
        if isinstance(league, dict)
        else "",
        "kickoff": str(row.get("date", "")),
        "status": str(row.get("status", "")),
        "replacement": str(row.get("replacedBy") or ""),
    }


async def request(
    path: str, params: dict[str, str], *, authenticated: bool = True
) -> object:
    if authenticated:
        key = os.environ.get("ODDS_API_IO_KEY", "").strip()
        if not key:
            raise OddsUnavailable(
                "Live odds credentials are missing. Connect the odds feed securely, use manual prices, or explicitly enable the fictional demo."
            )
        params = {**params, "apiKey": key}
    try:
        async with httpx.AsyncClient(
            timeout=20, follow_redirects=False
        ) as client:
            response = await client.get(f"{BASE}/{path}", params=params)
        if response.status_code in {401, 403}:
            raise OddsUnavailable(
                "Odds feed authorization or subscription access failed. Check your connected feed access."
            )
        if response.status_code == 429:
            raise OddsUnavailable(
                "Odds feed rate limit reached. Wait before retrying; your inputs are retained."
            )
        if response.status_code >= 500:
            raise OddsUnavailable(
                "Odds feed is temporarily unavailable. Please retry later."
            )
        if response.status_code != 200:
            raise OddsUnavailable(
                "The odds feed could not fulfill this request. Check the selected fixture and feed access."
            )
        return response.json()
    except httpx.TimeoutException:
        raise OddsUnavailable(
            "Odds feed timed out. Please retry; your inputs are retained."
        ) from None
    except httpx.RequestError:
        raise OddsUnavailable(
            "Odds feed could not be reached. Please retry later."
        ) from None
    except ValueError:
        raise OddsUnavailable(
            "Odds feed returned an unreadable response. Please retry later."
        ) from None


async def catalogues() -> tuple[list[str], list[dict]]:
    books = await request("bookmakers", {}, authenticated=False)
    markets = await request(
        "markets", {"sport": "football"}, authenticated=False
    )
    if (
        not isinstance(books, list)
        or not isinstance(markets, dict)
        or not isinstance(markets.get("markets"), list)
    ):
        raise OddsUnavailable(
            "Odds catalogue format is unsupported. No bookmaker coverage is assumed."
        )
    names = [
        str(row.get("name", "")) if isinstance(row, dict) else str(row)
        for row in books
    ]
    supported = [name for name in ["SportyBet", "Bet9ja"] if name in names]
    if not supported:
        raise OddsUnavailable(
            "SportyBet and Bet9ja are unavailable in the current verified catalogue."
        )
    return supported, [
        row for row in markets["markets"] if isinstance(row, dict)
    ]


async def search_fixtures(
    start: str, end: str
) -> tuple[list[FixtureView], str]:
    if not available():
        raise OddsUnavailable(
            "Live odds credentials are missing. Connect the odds feed securely, use manual prices, or explicitly enable the fictional demo."
        )
    beginning, ending = utc_input(start), utc_input(end)
    if not timedelta(0) < ending - beginning <= timedelta(days=7):
        raise ValueError(
            "Choose an increasing UTC search window of at most 7 days."
        )
    books, _ = await catalogues()
    rows: list[FixtureView] = []
    limited = False
    for page in range(3):
        payload = await request(
            "events",
            {
                "sport": "football",
                "status": "pending",
                "from": beginning.isoformat(),
                "to": ending.isoformat(),
                "bookmaker": books[0],
                "limit": "500",
                "skip": str(page * 500),
            },
        )
        if not isinstance(payload, list):
            raise OddsUnavailable("Fixture response format is unsupported.")
        for item in payload:
            if isinstance(item, dict) and isinstance(item.get("id"), int):
                row = fixture_view(item)
                if row["home"] and row["away"]:
                    rows.append(row)
        if len(payload) < 500:
            break
        limited = page == 2
    scope = (
        "Limited to the first 1,500 results; narrow the window to search further."
        if limited
        else "No results here does not mean the fixture is unavailable globally. Club labels are shown exactly, including women/youth where supplied; verify category yourself."
    )
    return (
        rows,
        f"{len(rows)} fixtures in this UTC window from {books[0]}'s catalogue. {scope}",
    )


def comparison_key(row: QuoteView) -> tuple[str, ...]:
    return (
        row["event_id"],
        row["market"],
        row["outcome"],
        row["line"],
        row["period"],
        row["subject"],
        row["cards"],
        row["rules"],
    )


def mark_highest(rows: list[QuoteView]) -> list[QuoteView]:
    groups: dict[tuple[str, ...], list[QuoteView]] = {}
    for row in rows:
        row["highest"] = False
        if row["eligible"] and row["supported"] and row["price"]:
            key = comparison_key(row)
            if row["cards"] and (
                not row["rules"]
                or row["cards"] == "Settlement definition unknown"
            ):
                key = (*key, row["bookmaker"])
            groups.setdefault(key, []).append(row)
    for group in groups.values():
        if len({row["bookmaker"] for row in group}) < 2:
            continue
        highest = max(decimal_price(row["price"]) for row in group)
        for row in group:
            row["highest"] = decimal_price(row["price"]) == highest
    return rows


def parse_quotes(
    payload: dict, fixture: FixtureView, markets: list[dict], books: list[str]
) -> list[QuoteView]:
    actual = fixture_view(payload)
    if any(
        actual[key] != fixture[key]
        for key in ("id", "home", "away", "competition", "kickoff")
    ):
        raise OddsUnavailable(
            "The odds response fixture differs from your selected fixture. Search and select it again."
        )
    prematch(actual)
    catalog = {str(row.get("name", "")): row for row in markets}
    output: list[QuoteView] = []
    offered = payload.get("bookmakers") or {}
    urls = payload.get("urls") or {}
    if not isinstance(offered, dict):
        raise OddsUnavailable("Bookmaker response format is unsupported.")
    outcome_shapes = [
        {"home", "draw", "away"},
        {"home", "away"},
        {"over", "under"},
        {"yes", "no"},
        {"homeDraw", "homeAway", "drawAway"},
        {"home_draw", "home_away", "draw_away"},
        {"1X", "12", "X2"},
    ]
    metadata = {
        "max",
        "hdp",
        "line",
        "subject",
        "period",
        "settlementRules",
        "cardDefinition",
    }
    for book in books:
        book_markets = offered.get(book, [])
        if not isinstance(book_markets, list):
            continue
        for market_index, market in enumerate(book_markets):
            if not isinstance(market, dict):
                continue
            name = str(market.get("name", ""))
            definition = catalog.get(name, {})
            period = str(market.get("period") or definition.get("period") or "")
            observed = str(market.get("updatedAt") or "")
            age, fresh = freshness(observed)
            market_odds = market.get("odds", [])
            if not isinstance(market_odds, list):
                continue
            for line_index, line_row in enumerate(market_odds):
                if not isinstance(line_row, dict):
                    continue
                labels = set(line_row) - metadata
                known_shape = labels in outcome_shapes
                supported = bool(
                    definition
                    and period
                    and definition.get("prematch")
                    and known_shape
                )
                if (
                    "max" in line_row
                    and "hdp" in line_row
                    and str(line_row["max"]) != str(line_row["hdp"])
                ):
                    supported = False
                line = str(
                    line_row.get(
                        "line", line_row.get("hdp", line_row.get("max", ""))
                    )
                )
                cards = str(
                    market.get("cardDefinition")
                    or line_row.get("cardDefinition")
                    or (
                        "Settlement definition unknown"
                        if any(
                            word in name.lower() for word in ("card", "booking")
                        )
                        else ""
                    )
                )
                rules = str(
                    market.get("settlementRules")
                    or line_row.get("settlementRules")
                    or ""
                )
                for label in sorted(labels):
                    try:
                        price = (
                            format(decimal_price(str(line_row[label])), ".6f")
                            .rstrip("0")
                            .rstrip(".")
                        )
                    except ValueError:
                        price = ""
                    source_url = (
                        https_source(str(urls.get(book, "")))
                        if isinstance(urls, dict)
                        else ""
                    )
                    output.append(
                        {
                            "id": f"{book}:{market_index}:{line_index}:{label}",
                            "event_id": actual["id"],
                            "home": actual["home"],
                            "away": actual["away"],
                            "competition": actual["competition"],
                            "kickoff": actual["kickoff"],
                            "bookmaker": book,
                            "market": name,
                            "outcome": label,
                            "line": line,
                            "period": str(line_row.get("period") or period),
                            "subject": str(
                                line_row.get("subject")
                                or market.get("subject")
                                or ""
                            ),
                            "cards": cards,
                            "rules": rules,
                            "price": price,
                            "observed": observed,
                            "freshness": age,
                            "status": "verified"
                            if observed and fresh and supported and price
                            else "unverified",
                            "supported": supported,
                            "eligible": bool(fresh and supported and price),
                            "highest": False,
                            "source": "Odds-API.io",
                            "url": source_url,
                            "raw": json.dumps(line_row, ensure_ascii=True),
                            "note": "Settlement-rule gap: check operator rules before manual transfer."
                            if supported
                            else "Unsupported comparison shape or missing market/period catalogue. Raw labels retained; no normalized mapping assumed.",
                        }
                    )
    return mark_highest(output)


async def fetch_quotes(fixture: FixtureView) -> list[QuoteView]:
    if not available():
        raise OddsUnavailable(
            "Live odds credentials are missing. Connect an odds feed or use the explicit demo."
        )
    prematch(fixture)
    books, markets = await catalogues()
    payload = await request(
        "odds", {"eventId": fixture["id"], "bookmakers": ",".join(books)}
    )
    if not isinstance(payload, dict):
        raise OddsUnavailable("Odds response format is unsupported.")
    return parse_quotes(payload, fixture, markets, books)


def demo_quotes() -> list[QuoteView]:
    rows: list[QuoteView] = []
    for book, prices in [
        ("SportyBet", ["2.10", "3.40", "3.20"]),
        ("Bet9ja", ["2.15", "3.30", "3.15"]),
    ]:
        for outcome, price in zip(["home", "draw", "away"], prices):
            rows.append(
                {
                    "id": f"sample:{book}:{outcome}",
                    "event_id": "sample:northbridge-riverside",
                    "home": "Northbridge FC",
                    "away": "Riverside FC",
                    "competition": "Fictional demonstration league",
                    "kickoff": "2030-08-01T15:00:00Z",
                    "bookmaker": book,
                    "market": "ML",
                    "outcome": outcome,
                    "line": "",
                    "period": "match",
                    "subject": "",
                    "cards": "",
                    "rules": "Fictional sample: 90 minutes only",
                    "price": price,
                    "observed": "2025-01-01T12:00:00Z",
                    "freshness": "Fixed sample timestamp · not live",
                    "status": "sample",
                    "supported": True,
                    "eligible": True,
                    "highest": False,
                    "source": "Fictional demonstration",
                    "url": "",
                    "raw": "",
                    "note": "Sample only. No research evidence or real bookmaker coverage is asserted.",
                }
            )
    return mark_highest(rows)


def selection_view(row: SavedSelection) -> SelectionView:
    observed = row.observed_at.isoformat() if row.observed_at else ""
    age, fresh = freshness(observed, sample=row.is_sample)
    eligible = bool(row.decimal_odds and fresh and not row.is_live)
    if row.kickoff_at and not row.is_sample:
        eligible = eligible and row.kickoff_at > datetime.now(timezone.utc)
    elif not row.is_sample:
        eligible = False
    return {
        "id": str(row.id),
        "chat": str(row.research_chat_id or ""),
        "home": row.home_team,
        "away": row.away_team,
        "competition": row.competition,
        "kickoff": row.kickoff_at.isoformat() if row.kickoff_at else "",
        "market": row.market_name,
        "outcome": row.outcome_name,
        "line": row.line_label or "",
        "period": row.market_period,
        "subject": row.subject_name or "",
        "cards": row.card_definition or "",
        "rules": row.settlement_rules
        or str(
            (row.evidence_provenance or {}).get("user_settlement_notes", "")
        ),
        "bookmaker": row.bookmaker,
        "price": format(row.decimal_odds, ".6f").rstrip("0").rstrip(".")
        if row.decimal_odds
        else "",
        "observed": observed,
        "status": row.data_status,
        "rationale": row.research_rationale,
        "source": row.source_provider,
        "url": https_source(row.source_url),
        "event_id": row.canonical_event_id or "",
        "freshness": age,
        "eligible": eligible,
    }


def calculate(
    bankroll: str, risk: str, stake: str, price: str
) -> dict[str, str]:
    try:
        bank, percent = Decimal(bankroll), Decimal(risk)
        if (
            not bank.is_finite()
            or bank <= 0
            or not percent.is_finite()
            or not 0 < percent <= 2
        ):
            raise ValueError
        if bank.as_tuple().exponent < -2:
            raise ValueError
        maximum = (bank * percent / 100).quantize(
            Decimal("0.01"), rounding=ROUND_DOWN
        )
        amount = Decimal(stake) if stake.strip() else maximum
        if (
            not amount.is_finite()
            or amount <= 0
            or amount > maximum
            or amount.as_tuple().exponent < -2
        ):
            raise ValueError
        odds = decimal_price(price)
        gross = amount * odds
        if not math.isfinite(float(gross)):
            raise ValueError
        return {
            "maximum": f"₦{maximum:,.2f}",
            "stake": f"₦{amount:,.2f}",
            "gross": f"₦{gross:,.2f}",
            "profit": f"₦{gross - amount:,.2f}",
        }
    except (InvalidOperation, ValueError, OverflowError):
        raise ValueError(
            "Use a positive finite NGN bankroll, risk above 0 and at most 2%, valid odds >1, and a stake no higher than the suggested maximum."
        ) from None
