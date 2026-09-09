# -*- coding: utf-8 -*-
import os
import shutil
import unittest
import xmlrpc.client
from tempfile import mkdtemp
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ingestors.exc import ProcessingException
from ingestors.support.convert import DocumentConvertSupport

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "doc.doc")


def make_support(uri, timeout=5):
    """A bare DocumentConvertSupport: the unoserver code path only needs
    settings and a temp dir, no manager or cache."""
    support = DocumentConvertSupport.__new__(DocumentConvertSupport)
    support.settings = SimpleNamespace(unoserver_uri=uri, convert_timeout=timeout)
    return support


class UnoserverConvertTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_remote_uri_sends_bytes_and_writes_result(self):
        support = make_support("http://unoserver:2003")
        proxy = MagicMock()
        proxy.convert.return_value = xmlrpc.client.Binary(b"%PDF-1.4 fake")
        with patch("xmlrpc.client.ServerProxy", return_value=proxy):
            out = support._document_to_pdf(self.tmpdir, FIXTURE, "entity", timeout=5)
        args = proxy.convert.call_args[0]
        self.assertIsNone(args[0])  # inpath unused for remote listeners
        self.assertIsInstance(args[1], bytes)  # indata carries the document
        self.assertIsNone(args[2])  # outpath unused, PDF comes back as bytes
        self.assertEqual(args[3], "pdf")
        with open(out, "rb") as fh:
            self.assertEqual(fh.read(), b"%PDF-1.4 fake")

    def test_local_uri_passes_paths(self):
        support = make_support("http://localhost:2003")
        proxy = MagicMock()

        def fake_convert(inpath, indata, outpath, *rest):
            with open(outpath, "wb") as fh:
                fh.write(b"%PDF-1.4 fake")

        proxy.convert.side_effect = fake_convert
        with patch("xmlrpc.client.ServerProxy", return_value=proxy):
            out = support._document_to_pdf(self.tmpdir, FIXTURE, "entity", timeout=5)
        args = proxy.convert.call_args[0]
        self.assertEqual(args[0], os.path.abspath(FIXTURE))  # inpath, shared fs
        self.assertIsNone(args[1])  # no bytes copied over the wire
        self.assertEqual(args[2], out)

    def test_unreachable_listener_falls_back_to_spawn(self):
        support = make_support("http://unoserver:2003")
        support._document_to_pdf_spawn = MagicMock(return_value="spawned.pdf")
        proxy = MagicMock()
        proxy.convert.side_effect = ConnectionRefusedError("refused")
        with patch("xmlrpc.client.ServerProxy", return_value=proxy):
            out = support._document_to_pdf(self.tmpdir, FIXTURE, "entity", timeout=5)
        self.assertEqual(out, "spawned.pdf")
        support._document_to_pdf_spawn.assert_called_once()

    def test_conversion_fault_fails_without_fallback(self):
        # A document LibreOffice cannot convert fails the same through any
        # invocation path; retrying via spawn would just fail slower.
        support = make_support("http://unoserver:2003")
        support._document_to_pdf_spawn = MagicMock()
        proxy = MagicMock()
        proxy.convert.side_effect = xmlrpc.client.Fault(1, "Cannot open document")
        with patch("xmlrpc.client.ServerProxy", return_value=proxy):
            with self.assertRaises(ProcessingException):
                support._document_to_pdf(self.tmpdir, FIXTURE, "entity", timeout=5)
        support._document_to_pdf_spawn.assert_not_called()

    def test_no_uri_uses_spawn_path(self):
        support = make_support(None)
        support._document_to_pdf_spawn = MagicMock(return_value="spawned.pdf")
        out = support._document_to_pdf(self.tmpdir, FIXTURE, "entity", timeout=5)
        self.assertEqual(out, "spawned.pdf")

    @unittest.skipUnless(
        os.environ.get("INGESTORS_UNOSERVER_URI"),
        "integration: set INGESTORS_UNOSERVER_URI to a running unoserver",
    )
    def test_integration_real_unoserver(self):
        support = make_support(os.environ["INGESTORS_UNOSERVER_URI"], timeout=60)
        out = support._document_to_pdf(self.tmpdir, FIXTURE, "entity", timeout=60)
        with open(out, "rb") as fh:
            self.assertTrue(fh.read(5).startswith(b"%PDF-"))
