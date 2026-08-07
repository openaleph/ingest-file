from dataclasses import dataclass
import logging
import os
from typing import Dict, List, Optional
import uuid
import unicodedata

import fitz
from lxml import etree

from normality import collapse_spaces  # noqa

from followthemoney import model
from ingestors.exc import UnauthorizedError
from ingestors.support.ocr import OCRSupport
from ingestors.support.convert import DocumentConvertSupport
from ingestors.support.xml import XMLSupport

log = logging.getLogger(__name__)


@dataclass
class PdfPageModel:
    """Represents data extracted from a page in a PDF"""

    number: int
    text: str


@dataclass
class PdfModel:
    """Represents data extracted from a PDF"""

    metadata: Optional[Dict[str, str]]
    xmp_metadata: Optional[etree._Element]
    pages: List[PdfPageModel]


# context here https://github.com/adobe/XMP-Toolkit-SDK/blob/main/docs/XMPSpecificationPart2.pdf 
# and here https://github.com/adobe/XMP-Toolkit-SDK/blob/main/docs/XMPSpecificationPart3.pdf
XMP_NS = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "xmp": "http://ns.adobe.com/xap/1.0/",
    "pdf": "http://ns.adobe.com/pdf/1.3/",
    "xmpMM": "http://ns.adobe.com/xap/1.0/mm/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
}


class PDFSupport(DocumentConvertSupport, OCRSupport, XMLSupport):
    """Provides helpers for PDF file context extraction."""

    def parse_xmp_metadata(self, xmp_string: str) -> Optional[etree._Element]:
        if not xmp_string:
            return None
        return self.parse_xml_string(xmp_string)

    def _xmp_find(self, tree: etree._Element, xpath: str):
        el = tree.find(xpath, namespaces=XMP_NS)
        if el is None:
            return None
        # plain text
        if el.text and el.text.strip():
            return el.text.strip()
        # rdf:Alt or rdf:Seq — return all li values
        items = el.findall("./rdf:Alt/rdf:li", namespaces=XMP_NS)
        if not items:
            items = el.findall("./rdf:Seq/rdf:li", namespaces=XMP_NS)
        if items:
            return [li.text.strip() for li in items if li.text]
        return None

    def extract_xmp_metadata(self, pdf: PdfModel, entity):
        if pdf.xmp_metadata is None:
            return
        try:
            tree = pdf.xmp_metadata
            entity.add("messageId", self._xmp_find(tree, ".//xmpMM:DocumentID"))
            entity.add("title", self._xmp_find(tree, ".//dc:title"))
            entity.add("author", self._xmp_find(tree, ".//dc:creator"))
            entity.add("generator", self._xmp_find(tree, ".//pdf:Producer"))
            entity.add("language", self._xmp_find(tree, ".//dc:language"))
            entity.add("authoredAt", self._xmp_find(tree, ".//xmp:CreateDate"))
            entity.add("modifiedAt", self._xmp_find(tree, ".//xmp:ModifyDate"))
        except Exception as ex:
            log.warning("Error reading XMP: %r", ex)

    def extract_metadata(self, pdf: PdfModel, entity):
        meta = pdf.metadata
        if meta is not None:
            entity.add("title", meta.get("title"))
            entity.add("author", meta.get("author"))
            entity.add("generator", meta.get("creator"))
            entity.add("generator", meta.get("producer"))
            entity.add("keywords", meta.get("subject"))

    def extract_pages(self, pdf_model: PdfModel, entity, manager):
        entity.schema = model.get("Pages")
        for page_model in pdf_model.pages:
            page_entity = self.manager.make_entity("Page")
            page_entity.make_id(entity.id, page_model.number)
            page_entity.set("document", entity)
            page_entity.set("index", page_model.number)
            page_entity.add("bodyText", page_model.text)
            manager.apply_context(page_entity, entity)
            manager.emit_entity(page_entity)
            manager.emit_text_fragment(entity, page_model.text, page_entity.id)

    def parse(self, file_path: str) -> PdfModel:
        """Takes a file_path to a pdf and returns a `PdfModel`"""
        pdf_model = PdfModel(metadata=None, xmp_metadata=None, pages=[])
        with fitz.open(file_path) as pdf_doc:
            if pdf_doc.needs_pass:
                raise UnauthorizedError
            pdf_model.metadata = pdf_doc.metadata
            pdf_model.xmp_metadata = self.parse_xmp_metadata(pdf_doc.get_xml_metadata())
            for page in pdf_doc:
                pdf_model.pages.append(
                    self.pdf_extract_page(pdf_doc, page, page.number + 1)
                )
        return pdf_model

    def parse_and_ingest(self, file_path: str, entity, manager):
        pdf_model: PdfModel = self.parse(file_path)
        self.extract_metadata(pdf_model, entity)
        self.extract_xmp_metadata(pdf_model, entity)
        self.extract_pages(pdf_model, entity, manager)

    def pdf_alternative_extract(self, entity, pdf_path: str, manager):
        checksum = self.manager.store(pdf_path)
        entity.set("pdfHash", checksum)
        self.parse_and_ingest(pdf_path, entity, manager)

    def pdf_extract_page(
        self, pdf_doc: fitz.Document, page: fitz.Page, page_number: int
    ) -> PdfPageModel:
        """Extract the contents of a single PDF page, using OCR if need be."""
        # Extract text
        fonts = page.get_fonts()
        # For pages with Type3 fonts we extract an image of the page and OCR it
        type3_fonts: bool = any([font[2] == "Type3" for font in fonts])
        if type3_fonts:
            full_text = ""
        else:
            full_text = page.get_text(textpage=None, sort=True)

        # Extract images
        images = page.get_images()

        # Create a temporary location to store all extracted images
        temp_dir = self.make_empty_directory()
        image_dir = temp_dir.joinpath(str(uuid.uuid4()))
        os.mkdir(image_dir)

        # Extract images from PDF and store them on the disk
        extracted_images = []
        if type3_fonts:
            filename = image_dir / f"page-{page.number}.png"
            image = page.get_pixmap(dpi=300).save(filename)
            extracted_images.append(filename)
        else:
            for image_index, image in enumerate(images, start=1):
                xref = image[0]
                img = pdf_doc.extract_image(xref)
                if img:
                    image_path = os.path.join(
                        image_dir, f"image{page_number}_{image_index}.{img['ext']}"
                    )
                    with open(image_path, "wb") as image_file:
                        image_file.write(img["image"])
                    extracted_images.append(image_path)

        # Attempt to OCR the images and extract text
        languages = self.manager.context.get("languages")
        for image_path in extracted_images:
            with open(image_path, "rb") as fh:
                data = fh.read()
                text = self.extract_ocr_text(data, languages=languages)
                if text is not None:
                    # print(f"[IF] extracted text from images: \n{text}")
                    full_text += text
        # print(f"Extracted {len(extracted_images)} images")
        full_text = unicodedata.normalize("NFKD", full_text.strip())
        return PdfPageModel(number=page_number, text=full_text.strip())
