import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from ingestors.support.xfa import is_xfa, render_xfa_to_pdf
from tests.support import TestCase

FIXTURES = Path(__file__).parent / "fixtures"


class IsXfaTest(unittest.TestCase):
    def test_xfa_pdf_detected(self):
        with fitz.open(str(FIXTURES / "minimal-xfa.pdf")) as doc:
            self.assertTrue(is_xfa(doc))

    def test_non_xfa_pdf_not_detected(self):
        with fitz.open(str(FIXTURES / "readme.pdf")) as doc:
            self.assertFalse(is_xfa(doc))


class RenderXfaTest(unittest.TestCase):
    def test_returns_false_when_pypdfium2_missing(self):
        # pypdfium2 is not installed in this environment; the function must
        # degrade gracefully rather than raise.
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.pdf"
            result = render_xfa_to_pdf(FIXTURES / "minimal-xfa.pdf", out)
        self.assertFalse(result)

    def test_returns_false_when_pdfium_lacks_xfa(self):
        # Simulate pypdfium2 present but compiled without XFA/V8.
        import types

        fake_pdfium = types.ModuleType("pypdfium2.raw")
        fake_pdfium.PDFIUM_INFO = type("I", (), {"flags": ["PDF"]})()

        fake_top = types.ModuleType("pypdfium2")

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.pdf"
            with (
                patch.dict(
                    "sys.modules",
                    {"pypdfium2": fake_top, "pypdfium2.raw": fake_pdfium},
                ),
            ):
                result = render_xfa_to_pdf(FIXTURES / "minimal-xfa.pdf", out)
        self.assertFalse(result)


class XfaIngestFallbackTest(TestCase):
    """Integration test: when pypdfium2 is unavailable the ingestor must fall
    back to ordinary fitz extraction instead of failing the ingest."""

    def test_xfa_pdf_ingested_as_pages(self):
        fixture_path, entity = self.fixture("minimal-xfa.pdf")
        self.manager.ingest(fixture_path, entity)

        self.assertSuccess(entity)
        self.assertEqual(entity.schema.name, "Pages")
        # The placeholder page must have produced at least one Page child.
        emitted = self.get_emitted()
        page_entities = [e for e in emitted if e.schema.name == "Page"]
        self.assertGreaterEqual(len(page_entities), 1)

    def test_non_xfa_pdf_unaffected(self):
        # Regression guard: a plain PDF must not go through the XFA path.
        fixture_path, entity = self.fixture("readme.pdf")
        self.manager.ingest(fixture_path, entity)

        self.assertSuccess(entity)
        self.assertEqual(entity.schema.name, "Pages")
        emitted = self.get_emitted()
        page_entities = [e for e in emitted if e.schema.name == "Page"]
        self.assertGreaterEqual(len(page_entities), 1)
