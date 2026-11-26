import reflex as rx

import asyncio
import sys
import unittest
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.repositories import owned_messages_statement
from app.research_service import (
    ResearchUnavailable,
    extract_result,
    research,
    safe_url,
    service_available,
    source_records,
)


class URLSafetyTests(unittest.TestCase):
    def test_only_absolute_http_links(self):
        for value in (
            "javascript:alert(1)",
            "data:text/html,test",
            "file:///tmp/test",
            "//example.org",
            "/relative",
            "https://",
            "https://user:pass@example.org",
            "https://example.org\\@evil.test",
            "https://example.org\n/path",
            "https://example.org:bad/path",
            "https://[broken",
        ):
            with self.subTest(value=value):
                self.assertEqual(safe_url(value), "")
        for value in (
            "https://example.org/report?season=2026#cards",
            "http://example.org/report",
        ):
            self.assertEqual(safe_url(value), value)

    def test_sources_are_filtered_and_deduplicated(self):
        records = source_records(
            [
                {"url": "javascript:alert(1)", "title": "unsafe"},
                {
                    "url": "https://example.org/fixture",
                    "title": "Fixture",
                    "kind": "citation",
                },
                {"url": "https://example.org/fixture", "title": "Duplicate"},
            ]
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["kind"], "citation")

    def test_citation_parser_and_gaps(self):
        result = extract_result(
            {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Please provide the date.\n\n## Evidence gaps\n- Fixture date missing.",
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "url": "https://example.org/fixture",
                                        "title": "Fixture",
                                    },
                                    {
                                        "type": "url_citation",
                                        "url": "javascript:alert(1)",
                                        "title": "Bad",
                                    },
                                ],
                            }
                        ],
                    },
                    {
                        "type": "web_search_call",
                        "action": {
                            "sources": [{"url": "https://example.org/context"}]
                        },
                    },
                ],
            }
        )
        self.assertEqual(len(result["sources"]), 2)
        self.assertEqual(result["sources"][1]["kind"], "consulted")
        self.assertEqual(result["gaps"], ["Fixture date missing."])
        self.assertEqual(result["status"], "live")
        self.assertTrue(result["researched_at"].endswith("UTC"))

    def test_incomplete_output_is_not_success(self):
        with self.assertRaises(ResearchUnavailable):
            extract_result({"status": "incomplete", "output": []})

    def test_unsubstantiated_output_has_explicit_gap(self):
        result = extract_result(
            {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Please clarify the fixture.",
                                "annotations": [],
                            }
                        ],
                    }
                ],
            }
        )
        self.assertIn("No safe web source", result["gaps"][0])


class ResearchServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_sample_never_researches_real_prompt(self):
        result = await research(
            [{"role": "user", "content": "Real Club A vs Real Club B today"}],
            sample=True,
        )
        self.assertIn("Northbridge FC vs Riverside FC", result["content"])
        self.assertIn("No live analysis was performed", result["content"])
        self.assertNotIn("Real Club A", result["content"])
        self.assertEqual(result["status"], "sample")
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["researched_at"], "")
        self.assertGreater(len(result["gaps"]), 0)

    async def test_actual_missing_service_fails_without_fake_live_reply(self):
        if service_available():
            self.skipTest(
                "Missing-service test requires an environment without live service access; no provider is mocked."
            )
        with self.assertRaisesRegex(
            ResearchUnavailable, "Live analysis is unavailable"
        ):
            await research([{"role": "user", "content": "Research a fixture"}])


class RepositoryQueryTests(unittest.TestCase):
    def test_messages_require_owned_chat_join(self):
        query = owned_messages_statement(uuid4(), "test-owner")
        compiled = query.compile(dialect=postgresql.dialect())
        sql = str(compiled)
        self.assertIn(
            "JOIN research_chat ON chat_message.chat_id = research_chat.id", sql
        )
        self.assertIn("research_chat.owner_sub =", sql)
        self.assertIn("test-owner", compiled.params.values())


if __name__ == "__main__":
    compile_requested = "--compile" in sys.argv
    if compile_requested:
        sys.argv.remove("--compile")
    suite = unittest.defaultTestLoader.loadTestsFromModule(
        sys.modules[__name__]
    )
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    if not outcome.wasSuccessful():
        raise SystemExit(1)
    if compile_requested:
        from app.app import app

        app._compile()
        print("Reflex compilation completed.")
