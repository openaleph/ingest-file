import logging
import threading
import time
from contextlib import contextmanager
from functools import cache
from hashlib import sha1
from io import BytesIO

from normality import stringify
from PIL import Image
from rigour.langs import list_to_alpha3 as alpha3

from ingestors.support.cache import CacheSupport
from ingestors.util import temp_locale

log = logging.getLogger(__name__)
TESSERACT_LOCALE = "C"


def init_ocr() -> None:
    """Import tesserocr while still on the main thread.

    tesserocr initialises cysignals on import, which installs signal handlers,
    and `signal.signal` raises "signal only works in main thread of the main
    interpreter" anywhere else. Procrastinate runs sync tasks in a worker
    thread (`sync_to_async(..., thread_sensitive=False)`) and the ingestor
    modules are only imported when the auction first runs, so without this the
    import lands in that thread and every OCR attempt fails.
    """
    try:
        import tesserocr  # noqa: F401
    except Exception as exc:
        log.warning("Cannot initialise OCR engine: %s", exc)


@cache
def get_ocr_service() -> "LocalOCRService":
    return LocalOCRService()


@cache
def get_ocr_supported():
    with temp_locale(TESSERACT_LOCALE):
        # Tesseract language types:
        from tesserocr import get_languages

        _, ocr_supported = get_languages()
        log.info("OCR languages: %r", ocr_supported)
        return ocr_supported


class OCRSupport(CacheSupport):
    MIN_SIZE = 1024 * 2
    MAX_SIZE = (1024 * 1024 * 30) - 1024

    def extract_ocr_text(self, data, languages=None):
        if not self.MIN_SIZE < len(data) < self.MAX_SIZE:
            log.info("OCR: file size out of range (%d)", len(data))
            return None

        languages = sorted(set(languages or []))
        data_key = sha1(data).hexdigest()
        key = self.cache_key("ocr", data_key, *languages)
        text = self.tags.get(key)
        if text is not None:
            log.info("OCR: %s chars cached", len(text))
            return stringify(text)

        ocr_service = get_ocr_service()
        text = ocr_service.extract_text(data, languages=languages)
        if text is not None:
            self.tags.set(key, text)
            log.info("OCR: %s chars (from %s bytes)", len(text), len(data))
        return stringify(text)


class LocalOCRService(object):
    """Perform OCR using an RPC-based service."""

    MAX_MODELS = 4

    def __init__(self):
        self.tl = threading.local()

    def language_list(self, languages):
        models = [c for c in alpha3(languages) if c in get_ocr_supported()]
        if len(models) > self.MAX_MODELS:
            log.warning("Too many models, limit: %s", self.MAX_MODELS)
            models = models[: self.MAX_MODELS]
        models.append("eng")
        return "+".join(sorted(set(models)))

    def configure_engine(self, languages):
        from tesserocr import OEM, PSM, PyTessBaseAPI

        if not hasattr(self.tl, "api") or self.tl.api is None:
            log.info("Configuring OCR engine (%s)", languages)
            self.tl.api = PyTessBaseAPI(
                lang=languages, oem=OEM.LSTM_ONLY, psm=PSM.AUTO_OSD
            )
        if languages != self.tl.api.GetInitLanguagesAsString():
            log.info("Re-initialising OCR engine (%s)", languages)
            self.tl.api.Init(lang=languages, oem=OEM.LSTM_ONLY)
        return self.tl.api

    def extract_text(self, data, languages=None):
        """Extract text from a binary string of data."""
        image = None
        try:
            image = Image.open(BytesIO(data))
            image.load()
            # tesserocr re-encodes the image in its source format and decodes it
            # again through leptonica. The manylinux wheels bundle a leptonica
            # built without GIF and JPEG-2000 support, so those formats fail with
            # "pixReadMem: function not present". Clearing the format makes
            # tesserocr take its format-agnostic path instead.
            image.format = None
        except Exception as exc:
            log.exception("Cannot open image data using Pillow: %s", exc)
            return None

        try:
            with temp_locale(TESSERACT_LOCALE):
                languages = self.language_list(languages)
                with self.engine(languages) as api:
                    # TODO: play with contrast and sharpening the images.
                    if image.mode not in ("RGB", "RGBA", "L"):
                        image = image.convert("RGB")
                    start_time = time.time()
                    api.SetImage(image)
                    text = api.GetUTF8Text()
                    confidence = api.MeanTextConf()
                    end_time = time.time()
                    duration = end_time - start_time
                    log.info(
                        "w: %s, h: %s, l: %s, c: %s, took: %.5f",
                        image.width,
                        image.height,
                        languages,
                        confidence,
                        duration,
                    )
                    return text
        except Exception as exc:
            # returning None (not "") so that `extract_ocr_text` doesn't cache
            # the failure for this content hash
            log.exception("OCR error: %s", exc)
            return None
        finally:
            if image is not None:
                image.close()

    @contextmanager
    def engine(self, languages):
        """Context manager for OCR engine that ensures cleanup."""
        api = None
        try:
            api = self.configure_engine(languages)
            yield api
        finally:
            if api is not None:
                try:
                    api.Clear()
                except Exception as exc:
                    log.warning("Error clearing OCR engine: %s", exc)

    def __del__(self):
        """Clean up thread-local OCR resources when the service is destroyed."""
        if hasattr(self.tl, "api") and self.tl.api is not None:
            log.info("Cleaning up OCR engine for current thread")
            try:
                self.tl.api.End()
            except Exception as exc:
                log.warning("Error cleaning up OCR engine: %s", exc)
            finally:
                self.tl.api = None
