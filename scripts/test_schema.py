import reflex as rx

import unittest
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Numeric
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateTable

from app.models import Base, ChatMessage, ResearchChat, SavedSelection


class SchemaTests(unittest.TestCase):
    def test_tables_and_postgres_compilation(self):
        configure_mappers()
        self.assertEqual(
            set(Base.metadata.tables),
            {"research_chat", "chat_message", "saved_selection"},
        )
        for table in Base.metadata.sorted_tables:
            self.assertTrue(
                str(CreateTable(table).compile(dialect=postgresql.dialect()))
            )

    def test_nullable_precise_odds_and_line(self):
        for name in ("decimal_odds", "line"):
            column = SavedSelection.__table__.c[name]
            self.assertTrue(column.nullable)
            self.assertIsInstance(column.type, Numeric)
            self.assertEqual(column.type.scale, 6)
        selection = SavedSelection(decimal_odds=Decimal("1.875000"))
        self.assertEqual(selection.decimal_odds, Decimal("1.875000"))
        self.assertTrue(SavedSelection.__table__.c.research_chat_id.nullable)

    def test_owner_link_and_message_cascade(self):
        constraints = [
            c
            for c in SavedSelection.__table__.constraints
            if isinstance(c, ForeignKeyConstraint)
        ]
        self.assertEqual(len(constraints), 1)
        self.assertEqual(
            list(constraints[0].column_keys), ["research_chat_id", "owner_sub"]
        )
        self.assertEqual(constraints[0].ondelete, "RESTRICT")
        self.assertEqual(
            next(iter(ChatMessage.__table__.c.chat_id.foreign_keys)).ondelete,
            "CASCADE",
        )
        self.assertIn("delete-orphan", ResearchChat.messages.property.cascade)

    def test_integrity_guardrails_present(self):
        checks = {
            c.name: str(c.sqltext)
            for c in SavedSelection.__table__.constraints
            if isinstance(c, CheckConstraint)
        }
        for name in (
            "valid_bookmaker",
            "valid_status",
            "sample_status_consistent",
            "sample_never_live",
            "valid_decimal_odds",
            "verified_evidence_required",
            "odds_observation_required",
        ):
            self.assertIn(f"ck_saved_selection_{name}", checks)
        self.assertIn(
            "NOT (is_sample AND is_live)",
            checks["ck_saved_selection_sample_never_live"],
        )
        self.assertEqual(
            SavedSelection.__table__.c.data_status.server_default.arg, "manual"
        )

    def test_timezone_aware_and_indexed(self):
        for table in Base.metadata.tables.values():
            self.assertTrue(table.c.created_at.type.timezone)
            self.assertTrue(table.c.updated_at.type.timezone)
            self.assertTrue(table.indexes)
        self.assertTrue(SavedSelection.__table__.c.observed_at.type.timezone)
        self.assertTrue(SavedSelection.__table__.c.kickoff_at.type.timezone)


if __name__ == "__main__":
    unittest.main()
