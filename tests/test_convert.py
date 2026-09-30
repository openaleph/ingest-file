# -*- coding: utf-8 -*-
import os
import shutil
import threading
import unittest
import xmlrpc.client
from tempfile import mkdtemp
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ingestors.exc import ProcessingException
from ingestors.support.convert import (
    LISTENER_GRACE,
    DocumentConvertSupport,
    InlineUnoserver,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "doc.doc")


class FakeProcess:
    """Stands in for a started unoserver listener."""

    def __init__(self):
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


def fake_start(listener, timeout):
    listener.uri = "http://127.0.0.1:2999"
    listener.process = FakeProcess()
    InlineUnoserver._running.add(listener)


def write_pdf(inpath, indata, outpath, *rest):
    """A local listener's `convert`: it writes the PDF to the given path."""
    with open(outpath, "wb") as fh:
        fh.write(b"%PDF-1.4 fake")


def make_support(uri, timeout=5):
    """A bare DocumentConvertSupport: the unoserver code path only needs
    settings and a temp dir, no manager or cache."""
    support = DocumentConvertSupport.__new__(DocumentConvertSupport)
    support.settings = SimpleNamespace(unoserver_uri=uri, convert_timeout=timeout)
    return support


class UnoserverConvertTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = mkdtemp()
        # no listener carried over from another test in this thread
        InlineUnoserver._local = threading.local()

    def tearDown(self):
        # nor handed on to the next test, e.g. a fake one
        InlineUnoserver.stop_all()
        InlineUnoserver._local = threading.local()
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
        proxy.convert.side_effect = write_pdf
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

    def test_output_path_unique_per_call(self):
        # listeners outlive a conversion: two calls with the same directory
        # must never write to, or pick up, the same file
        support = make_support("http://localhost:2003")
        proxy = MagicMock()
        proxy.convert.side_effect = write_pdf
        with patch("xmlrpc.client.ServerProxy", return_value=proxy):
            first = support._document_to_pdf(self.tmpdir, FIXTURE, "entity", 5)
            second = support._document_to_pdf(self.tmpdir, FIXTURE, "entity", 5)
        self.assertNotEqual(first, second)

    @patch.object(InlineUnoserver, "start", autospec=True, side_effect=fake_start)
    def test_no_uri_uses_thread_listener(self, start):
        """Without a configured uri, the thread's own listener is started on
        the first conversion and kept for the next ones."""
        support = make_support(None)
        support._document_to_pdf_spawn = MagicMock()
        proxy = MagicMock()
        proxy.convert.side_effect = write_pdf
        with patch("xmlrpc.client.ServerProxy", return_value=proxy) as server:
            support._document_to_pdf(self.tmpdir, FIXTURE, "entity", timeout=5)
            support._document_to_pdf(self.tmpdir, FIXTURE, "entity", timeout=5)
        start.assert_called_once()
        support._document_to_pdf_spawn.assert_not_called()
        uri = server.call_args.args[0]
        self.assertEqual(uri, "http://127.0.0.1:2999")
        # the listener gives up on a conversion first, the client waits longer
        self.assertEqual(start.call_args.args[1], 5)
        timeout = server.call_args.kwargs["transport"]._timeout
        self.assertEqual(timeout, 5 + LISTENER_GRACE)
        # a local listener: handed paths, not bytes
        self.assertEqual(proxy.convert.call_args.args[0], os.path.abspath(FIXTURE))

    def test_threads_get_own_listeners(self):
        listeners = []
        thread = threading.Thread(
            target=lambda: listeners.append(InlineUnoserver.for_thread())
        )
        thread.start()
        thread.join()
        self.assertIs(InlineUnoserver.for_thread(), InlineUnoserver.for_thread())
        self.assertIsNot(listeners[0], InlineUnoserver.for_thread())

    @patch.object(InlineUnoserver, "start", autospec=True, side_effect=fake_start)
    def test_listener_of_ended_thread_is_stopped(self, start):
        thread = threading.Thread(target=lambda: InlineUnoserver.for_thread().ensure(5))
        thread.start()
        thread.join()
        (orphaned,) = InlineUnoserver._running
        self.assertIsNone(orphaned.process.poll())
        InlineUnoserver.for_thread().ensure(5)
        self.assertEqual(orphaned.process.poll(), -15)
        self.assertNotIn(orphaned, InlineUnoserver._running)

    @patch("ingestors.support.convert.shutil.which", return_value=None)
    def test_listener_start_failure_spawns(self, which):
        """A listener that can't be started isn't tried again for every
        document, the thread spawns LibreOffice instead."""
        support = make_support(None)
        support._document_to_pdf_spawn = MagicMock(return_value="spawned.pdf")
        for _ in range(2):
            out = support._document_to_pdf(self.tmpdir, FIXTURE, "entity", 5)
            self.assertEqual(out, "spawned.pdf")
        which.assert_called_once()
        self.assertEqual(support._document_to_pdf_spawn.call_count, 2)

    @patch.object(InlineUnoserver, "start", autospec=True, side_effect=fake_start)
    def test_wedged_listener_is_replaced(self, start):
        """A listener that stops answering falls back to spawning for this
        document, and is replaced for the next one."""
        support = make_support(None)
        support._document_to_pdf_spawn = MagicMock(return_value="spawned.pdf")
        proxy = MagicMock()
        proxy.convert.side_effect = TimeoutError("timed out")
        with patch("xmlrpc.client.ServerProxy", return_value=proxy):
            out = support._document_to_pdf(self.tmpdir, FIXTURE, "entity", 5)
            self.assertEqual(out, "spawned.pdf")
            listener = InlineUnoserver.for_thread()
            self.assertEqual(listener.process.poll(), -15)  # stopped
            proxy.convert.side_effect = write_pdf
            out = support._document_to_pdf(self.tmpdir, FIXTURE, "entity", 5)
        self.assertEqual(start.call_count, 2)
        self.assertTrue(out.endswith(".pdf") and out != "spawned.pdf")

    @unittest.skipUnless(
        shutil.which("unoserver"),
        "integration: needs unoserver and LibreOffice (the docker image)",
    )
    def test_integration_inline_listener(self):
        support = make_support(None, timeout=60)
        support._document_to_pdf_spawn = MagicMock(side_effect=AssertionError)
        pids = set()
        for _ in range(2):
            out = support._document_to_pdf(self.tmpdir, FIXTURE, "entity", 60)
            with open(out, "rb") as fh:
                self.assertTrue(fh.read(5).startswith(b"%PDF-"))
            pids.add(InlineUnoserver.for_thread().process.pid)
        # one listener for both documents, started again once it has exited
        self.assertEqual(len(pids), 1)
        listener = InlineUnoserver.for_thread()
        pid = listener.process.pid
        listener.process.terminate()
        listener.process.wait(30)
        out = support._document_to_pdf(self.tmpdir, FIXTURE, "entity", 60)
        self.assertTrue(os.path.getsize(out) > 0)
        self.assertNotEqual(listener.process.pid, pid)

    @unittest.skipUnless(
        os.environ.get("INGESTORS_UNOSERVER_URI"),
        "integration: set INGESTORS_UNOSERVER_URI to a running unoserver",
    )
    def test_integration_real_unoserver(self):
        support = make_support(os.environ["INGESTORS_UNOSERVER_URI"], timeout=60)
        out = support._document_to_pdf(self.tmpdir, FIXTURE, "entity", timeout=60)
        with open(out, "rb") as fh:
            self.assertTrue(fh.read(5).startswith(b"%PDF-"))
