import ctypes
import logging

log = logging.getLogger(__name__)


def is_xfa(pdf_doc) -> bool:
    """
    Return True if the document contains an XFA form.
    Expects fitz pdf_doc object.
    """
    try:
        acroform = pdf_doc.pdf_catalog()
        if acroform in (0, None):
            return False
        # xref_get_key resolves /AcroForm (may be an indirect ref) then /XFA.
        kind, value = pdf_doc.xref_get_key(acroform, "AcroForm")
        if kind == "xref":
            # indirect reference like "12 0 R" -> take the object number
            acroform_xref = int(value.split()[0])
        elif kind == "dict":
            acroform_xref = acroform
        else:
            return False
        kind, _ = pdf_doc.xref_get_key(acroform_xref, "XFA")
        return kind != "null"
    except Exception as ex:
        log.warning("Could not test for XFA form: %r", ex)
        return False


def _pdfium_has_xfa(pdfium) -> bool:
    try:
        return "XFA" in pdfium.PDFIUM_INFO.flags
    except Exception:
        return False


def render_xfa_to_pdf(file_path, out_path, dpi: float = 100.0) -> bool:
    """Render a (dynamic) XFA PDF into an image-wrapped PDF at ``out_path``.

    Returns True on success, False if pypdfium2 is missing, lacks XFA support,
    or rendering produced no pages -- in every such case the caller should fall
    back to ordinary PDF extraction rather than fail the ingest.

    This is a port of the project's ``xfa_render.py`` MVP. It deliberately uses
    pypdfium2's *raw* ctypes API: the high-level ``PdfDocument`` does not drive
    the XFA sequence (``FPDF_LoadXFA``, the JS platform struct, the form-layer
    draw), so only that path turns the placeholder into the laid-out pages.
    Output is one rasterized page per page with no text layer -- dynamic XFA
    flattening (``FPDFPage_Flatten`` + ``FPDF_SaveAsCopy``) is unreliable and
    drops content, so we render + wrap. The downstream page extraction OCRs it.
    """
    try:
        import pypdfium2.raw as pdfium
        from pypdfium2 import PdfBitmap
    except ImportError:
        log.warning("pypdfium2 not installed; cannot render XFA form")
        return False

    if not _pdfium_has_xfa(pdfium):
        log.warning("pypdfium2 built without XFA/V8 support; cannot render XFA form")
        return False

    # version=2 selects the V8-aware config; m_pIsolate stays NULL so pdfium
    # makes its own isolate.
    cfg = pdfium.FPDF_LIBRARY_CONFIG()
    cfg.version = 2
    pdfium.FPDF_InitLibraryWithConfig(cfg)

    doc = None
    form = None
    # The JS platform struct must outlive `form`; keep a reference in scope.
    js = None
    try:
        doc = pdfium.FPDF_LoadDocument(str(file_path).encode("utf-8"), None)
        if not doc:
            log.warning(
                "pdfium could not load %s (error %d)",
                file_path,
                pdfium.FPDF_GetLastError(),
            )
            return False

        info = pdfium.FPDF_FORMFILLINFO()
        info.version = 2  # XFA-aware (version 1 is AcroForm only)
        # XFA runs JavaScript; pdfium only spins up the JS runtime when a JS
        # platform struct is supplied. An all-zero one is fine headless.
        js = pdfium.IPDF_JSPLATFORM()
        js.version = 3
        info.m_pJsPlatform = ctypes.pointer(js)
        form = pdfium.FPDFDOC_InitFormFillEnvironment(doc, info)

        ftype = pdfium.FPDF_GetFormType(doc)
        if ftype in (pdfium.FORMTYPE_XFA_FULL, pdfium.FORMTYPE_XFA_FOREGROUND):
            if not pdfium.FPDF_LoadXFA(doc):
                log.warning("FPDF_LoadXFA failed for %s", file_path)

        n = pdfium.FPDF_GetPageCount(doc)
        pages = []  # one RGB PIL image per page
        for i in range(n):
            page = pdfium.FPDF_LoadPage(doc, i)
            pdfium.FORM_OnAfterLoadPage(page, form)

            # PDF points (1/72 in) -> pixels at the requested dpi
            w = int(pdfium.FPDF_GetPageWidthF(page) * dpi / 72.0)
            h = int(pdfium.FPDF_GetPageHeightF(page) * dpi / 72.0)

            bitmap = PdfBitmap.new_native(w, h, pdfium.FPDFBitmap_BGRA)
            bitmap.fill_rect((255, 255, 255, 255), 0, 0, w, h)
            pdfium.FPDF_RenderPageBitmap(
                bitmap.raw, page, 0, 0, w, h, 0, pdfium.FPDF_ANNOT
            )
            # XFA content is drawn by the form layer, not the page content stream.
            pdfium.FPDF_FFLDraw(
                form, bitmap.raw, page, 0, 0, w, h, 0, pdfium.FPDF_ANNOT
            )

            pages.append(bitmap.to_pil().convert("RGB"))
            bitmap.close()
            pdfium.FORM_OnBeforeClosePage(page, form)
            pdfium.FPDF_ClosePage(page)

        if not pages:
            log.warning("XFA render produced no pages for %s", file_path)
            return False

        # PIL writes multi-page PDFs natively (no extra dependency);
        # resolution=dpi sizes each page in points to match the original.
        pages[0].save(
            str(out_path), save_all=True, append_images=pages[1:], resolution=dpi
        )
        return True
    finally:
        if form is not None:
            pdfium.FPDFDOC_ExitFormFillEnvironment(form)
        if doc is not None:
            pdfium.FPDF_CloseDocument(doc)
        pdfium.FPDF_DestroyLibrary()
        del js
