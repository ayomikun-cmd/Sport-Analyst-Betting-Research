import reflex as rx

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import httpx

from app.odds_service import (
    OddsUnavailable,
    calculate,
    comparison_key,
    decimal_price,
    demo_quotes,
    fixture_view,
    freshness,
    https_source,
    mark_highest,
    parse_quotes,
    prematch,
    request,
    search_fixtures,
)
from app.states.selections_state import SelectionsState


class CalculatorTests(unittest.TestCase):
    def test_default_one_percent_and_single_return(self):
        result = calculate("50000", "1", "", "2.10")
        self.assertEqual(
            result,
            {
                "maximum": "₦500.00",
                "stake": "₦500.00",
                "gross": "₦1,050.00",
                "profit": "₦550.00",
            },
        )
        self.assertEqual(
            calculate("50000", "0.5", "100", "2.10")["gross"], "₦210.00"
        )
        self.assertEqual(
            calculate("50000", "2", "", "2")["maximum"], "₦1,000.00"
        )
        self.assertEqual(calculate("100.99", "1", "", "2")["maximum"], "₦1.00")

    def test_boundaries(self):
        for bank, risk, stake, odds in [
            ("0", "1", "", "2"),
            ("-5", "1", "", "2"),
            ("NaN", "1", "", "2"),
            ("Infinity", "1", "", "2"),
            ("100", "0", "", "2"),
            ("100", "2.01", "", "2"),
            ("100", "NaN", "", "2"),
            ("100", "1", "1.01", "2"),
            ("100", "1", "NaN", "2"),
            ("100", "1", "-1", "2"),
            ("100", "1", "0.001", "2"),
            ("0.01", "1", "", "2"),
            ("100", "1", "", ""),
            ("100", "1", "", "1"),
            ("100", "1", "", "Infinity"),
        ]:
            with self.subTest(bank=bank, risk=risk, stake=stake, odds=odds):
                with self.assertRaises(ValueError):
                    calculate(bank, risk, stake, odds)
        for value in ["NaN", "-Infinity", "1", "0", "-2", "2.1234567"]:
            with self.assertRaises(ValueError):
                decimal_price(value)
        self.assertEqual(decimal_price("1.875"), Decimal("1.875"))


class ExactComparisonTests(unittest.TestCase):
    def test_demo_is_fictional_and_betking_absent(self):
        rows = demo_quotes()
        self.assertTrue(all(row["status"] == "sample" for row in rows))
        self.assertTrue(all(row["home"] == "Northbridge FC" for row in rows))
        self.assertTrue(
            all(row["observed"] == "2025-01-01T12:00:00Z" for row in rows)
        )
        self.assertNotIn("BetKing", [row["bookmaker"] for row in rows])
        self.assertEqual(
            next(
                row
                for row in rows
                if row["bookmaker"] == "Bet9ja" and row["outcome"] == "home"
            )["highest"],
            True,
        )

    def test_different_lines_periods_subjects_never_compare(self):
        base = demo_quotes()[0]
        for key, value in [
            ("line", "2.5"),
            ("period", "first-half"),
            ("subject", "Player A"),
            ("event_id", "different"),
            ("market", "Totals"),
            ("outcome", "away"),
            ("cards", "booking points"),
            ("rules", "extra time"),
        ]:
            other = {
                **base,
                "id": "other",
                "bookmaker": "Bet9ja",
                "price": "9.00",
                key: value,
            }
            self.assertNotEqual(comparison_key(base), comparison_key(other))
            self.assertFalse(
                any(row["highest"] for row in mark_highest([dict(base), other]))
            )
        a = {**base, "cards": "Settlement definition unknown", "rules": ""}
        b = {**a, "bookmaker": "Bet9ja", "price": "9.00"}
        self.assertFalse(any(row["highest"] for row in mark_highest([a, b])))

    def test_market_timestamp_and_unknown_shapes(self):
        now = datetime.now(timezone.utc)
        event = {
            "id": 123,
            "home": "Test A women",
            "away": "Test B women",
            "date": (now + timedelta(days=1)).isoformat(),
            "status": "pending",
            "league": {"name": "Test league"},
        }
        payload = {
            **event,
            "urls": {"SportyBet": "https://example.org/fixture"},
            "bookmakers": {
                "SportyBet": [
                    {
                        "name": "Totals",
                        "updatedAt": now.isoformat(),
                        "odds": [{"max": 2.5, "over": "1.90", "under": "2.10"}],
                    },
                    {
                        "name": "ML",
                        "odds": [
                            {"home": "2.10", "draw": "3.40", "away": "NaN"}
                        ],
                    },
                    {
                        "name": "Unknown",
                        "updatedAt": now.isoformat(),
                        "odds": [{"custom_label": "2.50"}],
                    },
                ]
            },
        }
        markets = [
            {"name": "Totals", "period": "match", "prematch": True},
            {"name": "ML", "period": "match", "prematch": True},
        ]
        rows = parse_quotes(
            payload, fixture_view(event), markets, ["SportyBet", "Bet9ja"]
        )
        totals = [row for row in rows if row["market"] == "Totals"]
        self.assertTrue(
            all(row["line"] == "2.5" and row["eligible"] for row in totals)
        )
        self.assertTrue(
            all(not row["eligible"] for row in rows if row["market"] == "ML")
        )
        self.assertEqual(
            next(
                row
                for row in rows
                if row["market"] == "ML" and row["outcome"] == "away"
            )["price"],
            "",
        )
        unknown = next(row for row in rows if row["market"] == "Unknown")
        self.assertEqual(unknown["outcome"], "custom_label")
        self.assertFalse(unknown["supported"])
        self.assertIn("custom_label", unknown["raw"])
        payload["home"] = "Different club"
        with self.assertRaises(OddsUnavailable):
            parse_quotes(payload, fixture_view(event), markets, ["SportyBet"])

    def test_freshness_status_and_url_safety(self):
        self.assertFalse(freshness("")[1])
        self.assertFalse(
            freshness(
                (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
            )[1]
        )
        self.assertEqual(
            https_source("https://example.org/?apiKey=do-not-reflect"), ""
        )
        self.assertEqual(https_source("http://example.org/fixture"), "")
        self.assertEqual(
            https_source("https://example.org/fixture"),
            "https://example.org/fixture",
        )
        base = {
            "id": "1",
            "home": "A",
            "away": "B",
            "competition": "Test",
            "kickoff": "2030-01-01T00:00:00Z",
            "status": "pending",
            "replacement": "",
        }
        for status in ["live", "cancelled", "settled", "finished", ""]:
            with self.assertRaises(OddsUnavailable):
                prematch({**base, "status": status})
        with self.assertRaisesRegex(OddsUnavailable, "explicitly select"):
            prematch({**base, "replacement": "2"})


class MissingCredentialsTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_key_without_network_or_auth_database(self):
        with patch.dict("os.environ", {"ODDS_API_IO_KEY": ""}):
            with self.assertRaisesRegex(
                OddsUnavailable, "credentials are missing"
            ):
                await search_fixtures("", "")
            with self.assertRaisesRegex(
                OddsUnavailable, "credentials are missing"
            ):
                await request("odds", {"eventId": "1"})
            state = SelectionsState()
            outcome = SelectionsState.search.fn(
                state, {"from": "2030-01-01T00:00", "to": "2030-01-02T00:00"}
            )
            self.assertIsNone(outcome)
            self.assertFalse(state.fetching)
            self.assertIn("credentials are missing", state.error)
            self.assertEqual(state.search_start, "2030-01-01T00:00")
            self.assertEqual(state.quotes, [])

    async def test_safe_http_errors_and_timeouts(self):
        class Client:
            def __init__(self, response=None, failure=None):
                self.response, self.failure = response, failure

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def get(self, *args, **kwargs):
                if self.failure:
                    raise self.failure
                return self.response

        for code, message in [
            (401, "authorization"),
            (403, "authorization"),
            (429, "rate limit"),
            (503, "temporarily unavailable"),
        ]:
            response = httpx.Response(
                code, text="secret response must not surface"
            )
            with (
                patch.dict(
                    "os.environ", {"ODDS_API_IO_KEY": "test-only-placeholder"}
                ),
                patch(
                    "app.odds_service.httpx.AsyncClient",
                    return_value=Client(response=response),
                ),
            ):
                with self.assertRaisesRegex(OddsUnavailable, message) as caught:
                    await request("odds", {"eventId": "1"})
                self.assertNotIn("secret", str(caught.exception))
                self.assertNotIn("apiKey", str(caught.exception))
        with (
            patch.dict(
                "os.environ", {"ODDS_API_IO_KEY": "test-only-placeholder"}
            ),
            patch(
                "app.odds_service.httpx.AsyncClient",
                return_value=Client(
                    failure=httpx.ReadTimeout("private request details")
                ),
            ),
        ):
            with self.assertRaisesRegex(OddsUnavailable, "timed out"):
                await request("odds", {"eventId": "1"})


if __name__ == "__main__":
    unittest.main()
