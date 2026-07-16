import logging
import os
import pathlib
import subprocess
import xmlrpc.client
from urllib.parse import urlsplit

from followthemoney.helpers import entity_filename
from prometheus_client import Counter

from ingestors.exc import ProcessingException
from ingestors.settings import Settings
from ingestors.support.cache import CacheSupport
from ingestors.support.temp import TempFileSupport

log = logging.getLogger(__name__)
settings = Settings()

LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


class UnoserverUnavailable(Exception):
    """The unoserver listener cannot be reached (or is wedged/busy past the
    conversion timeout). Callers degrade to the LibreOffice spawn path."""


class _TimeoutTransport(xmlrpc.client.Transport):
    """xmlrpc.client has no timeout support; a hung LibreOffice behind the
    listener must not block the worker forever."""

    def __init__(self, timeout):
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host):
        connection = super().make_connection(host)
        connection.timeout = self._timeout
        return connection


PDF_CACHE_ACCESSED = Counter(
    "ingestfile_pdf_cache_accessed",
    "Number of times the PDF cache has been accessed, by cache status",
    ["status"],
)


class DocumentConvertSupport(CacheSupport, TempFileSupport):
    """Provides helpers for UNO document conversion."""

    def document_to_pdf(self, unique_tmpdir, file_path, entity):
        key = self.cache_key("pdf", entity.first("contentHash"))
        pdf_hash = self.tags.get(key)
        if pdf_hash is not None:
            file_name = entity_filename(entity, extension="pdf")
            path = self.manager.load(pdf_hash, file_name=file_name)
            if path is not None:
                PDF_CACHE_ACCESSED.labels(status="hit").inc()
                log.info("Using PDF cache: %s", file_name)
                entity.set("pdfHash", pdf_hash)
                return path

        PDF_CACHE_ACCESSED.labels(status="miss").inc()
        pdf_file = self._document_to_pdf(unique_tmpdir, file_path, entity)
        if pdf_file is not None:
            content_hash = self.manager.store(pdf_file)
            entity.set("pdfHash", content_hash)
            self.tags.set(key, content_hash)
        return pdf_file

    def _document_to_pdf(
        self, unique_tmpdir, file_path, entity, timeout=settings.convert_timeout
    ):
        """Converts an office document to PDF."""
        if self.settings.unoserver_uri:
            try:
                return self._document_to_pdf_unoserver(
                    unique_tmpdir, file_path, entity, timeout
                )
            except UnoserverUnavailable as exc:
                log.warning(
                    "unoserver unavailable (%s), falling back to LibreOffice spawn",
                    exc,
                )
        return self._document_to_pdf_spawn(unique_tmpdir, file_path, entity, timeout)

    def _document_to_pdf_unoserver(self, unique_tmpdir, file_path, entity, timeout):
        """Convert through a persistent unoserver listener (XML-RPC, unoserver
        API v3) instead of paying a LibreOffice process start per document.

        One attempt, no retries: connection failures and timeouts raise
        UnoserverUnavailable so the caller degrades to the spawn path for
        this document only — a wedged or busy listener must never queue work
        behind it (see the convert-document history, alephdata/ingest-file#395).
        Conversion errors for broken/encrypted documents raise
        ProcessingException without touching the spawn path, since the spawn
        would fail on those all the same, just slower.
        """
        uri = self.settings.unoserver_uri
        log.info("Converting [%s] to PDF via unoserver", entity)
        out_file = os.path.join(unique_tmpdir, "converted.pdf")
        # A listener on localhost shares our filesystem: hand it paths and
        # let it read/write directly. A remote listener gets the bytes over
        # XML-RPC and returns the PDF the same way.
        local = urlsplit(uri).hostname in LOCAL_HOSTS
        inpath = os.path.abspath(str(file_path)) if local else None
        indata = None
        if not local:
            with open(file_path, "rb") as fh:
                indata = fh.read()
        proxy = xmlrpc.client.ServerProxy(
            uri, allow_none=True, transport=_TimeoutTransport(timeout)
        )
        try:
            # convert(inpath, indata, outpath, convert_to, filtername,
            #         filter_options, update_index, infiltername, password)
            result = proxy.convert(
                inpath,
                indata,
                out_file if local else None,
                "pdf",
                None,
                [],
                True,
                None,
                None,
            )
        except xmlrpc.client.Fault as exc:
            raise ProcessingException("Could not be converted to PDF") from exc
        except OSError as exc:
            raise UnoserverUnavailable(str(exc)) from exc
        if not local:
            data = result.data if result is not None else None
            if not data:
                raise ProcessingException("Could not be converted to PDF")
            with open(out_file, "wb") as fh:
                fh.write(data)
        if not os.path.exists(out_file) or os.stat(out_file).st_size == 0:
            raise ProcessingException("Could not be converted to PDF")
        log.info(f"Successfully converted {out_file} via unoserver")
        return out_file

    def _document_to_pdf_spawn(
        self, unique_tmpdir, file_path, entity, timeout=settings.convert_timeout
    ):
        """Converts an office document to PDF by spawning a fresh LibreOffice
        process per document."""
        file_name = entity_filename(entity)
        log.info("Converting [%s] to PDF", entity)

        pdf_output_dir = os.path.join(unique_tmpdir, "out")
        libreoffice_profile_dir = os.path.join(unique_tmpdir, "profile")
        pathlib.Path(pdf_output_dir).mkdir(parents=True)
        pathlib.Path(libreoffice_profile_dir).mkdir(parents=True)

        cmd = [
            "/usr/bin/libreoffice",
            '"-env:UserInstallation=file://{}"'.format(libreoffice_profile_dir),
            "--nologo",
            "--headless",
            "--nocrashreport",
            "--nodefault",
            "--norestore",
            "--nolockcheck",
            "--invisible",
            "--convert-to",
            "pdf",
            "--outdir",
            pdf_output_dir,
            file_path,
        ]
        try:
            log.info(f"Starting LibreOffice: {cmd} with timeout {timeout}")
            try:
                subprocess.run(cmd, timeout=timeout, check=True)
            except Exception as e:
                raise ProcessingException("Could not be converted to PDF") from e

            for file_name in os.listdir(pdf_output_dir):
                if not file_name.endswith(".pdf"):
                    continue
                out_file = os.path.join(pdf_output_dir, file_name)
                if os.stat(out_file).st_size == 0:
                    continue
                log.info(f"Successfully converted {out_file}")
                return out_file
            raise ProcessingException("Could not be converted to PDF")
        except Exception as e:
            raise ProcessingException("Could not be converted to PDF") from e
