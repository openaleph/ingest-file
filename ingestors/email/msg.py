import email
import logging
import subprocess
from email.errors import MessageError, MissingHeaderBodySeparatorDefect
from email.policy import default
from html import escape
from pathlib import Path
from tempfile import TemporaryDirectory

from followthemoney import model
from rigour.mime import normalize_mimetype
from servicelayer.archive.util import checksum as servicelayer_checksum

from ingestors.email.helpers import fix_rfc822
from ingestors.exc import ProcessingException
from ingestors.ingestor import Ingestor
from ingestors.support.email import EmailSupport
from ingestors.support.encoding import EncodingSupport

log = logging.getLogger(__name__)


class RFC822Ingestor(Ingestor, EmailSupport, EncodingSupport):
    MIME_TYPES = ["multipart/mixed", "message/rfc822"]
    BODY_HTML = "text/html"
    BODY_PLAIN = "text/plain"
    BODY_TYPES = [BODY_HTML, BODY_PLAIN]
    BODY_RFC822 = "message/rfc822"
    DISPLAY_HEADERS = ["from", "to", "cc", "bcc", "subject", "reply-to", "date"]
    EXTENSIONS = ["eml", "rfc822", "email", "msg"]
    SCORE = 7

    def has_alternative(self, parent, content_type):
        if not parent:
            return False

        if normalize_mimetype(parent.get_content_type()) != "multipart/alternative":
            return False

        for part in parent.get_payload():
            if normalize_mimetype(part.get_content_type()) == content_type:
                return True

        return False

    def make_html_alternative(self, text):
        if not text:
            return None

        return escape(text).strip().replace("\n", "<br>")

    def decode_part(self, part):
        charset = part.get_content_charset()
        payload = part.get_payload(decode=True)
        return self.decode_string(payload, charset)

    def parse_html_part(self, entity, part, parent):
        payload = self.decode_part(part)
        text = self.extract_html_content(
            entity, payload, extract_metadata=False, add_index_text=False
        )

        if not self.has_alternative(parent, "text/plain"):
            entity.add("bodyText", text)

    def parse_plaintext_part(self, entity, part, parent):
        payload = self.decode_part(part)
        entity.add("bodyText", payload)

        if not self.has_alternative(parent, "text/html"):
            html = self.make_html_alternative(payload)
            entity.add("bodyHtml", html)

    def parse_rfc822_part(self, entity, part, parent):
        msg = part.get_payload(0)
        headers = [
            f"{name}: {value}"
            for name, value in msg.items()
            if name.lower() in self.DISPLAY_HEADERS
        ]
        text = "\n".join(headers)
        html = self.make_html_alternative(text)
        entity.add("bodyText", text)
        entity.add("bodyHtml", html)

        self.parse_parts(entity, part)

    def parse_part(self, entity, part, parent):
        mime_type = normalize_mimetype(part.get_content_type())
        file_name = part.get_filename()
        is_body_type = mime_type in self.BODY_TYPES
        is_attachment = part.is_attachment()
        is_attachment = is_attachment or file_name is not None
        is_attachment = is_attachment or (not is_body_type and not part.is_multipart())

        if is_attachment:
            if part.is_multipart():
                # The attachment is an email
                if (
                    part.get_all("Content-Transfer-Encoding")
                    and part.get_all("Content-Transfer-Encoding")[0] == "base64"
                ):
                    import base64

                    payload = base64.b64decode(part.get_payload(i=0).get_payload())
                else:
                    payload = str(part.get_payload(i=0))
            else:
                payload = part.get_payload(decode=True)
            self.ingest_attachment(entity, file_name, mime_type, payload)
            return

        if self.BODY_RFC822 in mime_type:
            self.parse_rfc822_part(entity, part, parent)
            return

        if part.is_multipart():
            self.parse_parts(entity, part)
            return

        if self.BODY_HTML in mime_type:
            self.parse_html_part(entity, part, parent)
            return

        if self.BODY_PLAIN in mime_type:
            self.parse_plaintext_part(entity, part, parent)
            return

        log.error("Dangling MIME fragment: %s", part)

    def parse_parts(self, entity, parent):
        for part in parent.get_payload():
            self.parse_part(entity, part, parent)

    def ingest_msg(self, entity, msg):
        self.extract_msg_headers(entity, msg)
        self.resolve_message_ids(entity)

        if msg.is_multipart():
            self.parse_parts(entity, msg)
        else:
            self.parse_part(entity, msg, None)

    def ingest(self, file_path, entity):
        entity.schema = model.get("Email")
        try:
            with open(file_path, "rb") as fh:
                msg = email.message_from_binary_file(fh, policy=default)
        except (MessageError, ValueError, IndexError) as err:
            raise ProcessingException(f"Cannot parse email: {err}") from err

        if msg.defects and any(
            [isinstance(x, MissingHeaderBodySeparatorDefect) for x in msg.defects]
        ):
            fixed_email_string = fix_rfc822(file_path)
            try:
                msg = email.message_from_bytes(fixed_email_string, policy=default)
            except (MessageError, ValueError, IndexError) as err:
                raise ProcessingException(f"Cannot parse email: {err}") from err

        self.ingest_msg(entity, msg)

        ignore_prefix = "openaleph_ignore_nameless_attachment"
        with TemporaryDirectory() as temp_dir:
            # -p = prefix filename to be used on files without a filename
            # --prefix = rename by putting unique code at the front of the filename
            cmd = [
                "ripmime",
                "-q",
                "-i",
                file_path,
                "-d",
                temp_dir,
                "-p",
                ignore_prefix,
                "--prefix",
            ]
            try:
                subprocess.run(
                    cmd,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.STDOUT,
                )

                temp_dir_path = Path(temp_dir)
                for attachment_path in temp_dir_path.iterdir():
                    if not attachment_path.name.startswith(ignore_prefix):
                        content_hash = servicelayer_checksum(attachment_path)
                        if content_hash not in self.attachments_checksums:
                            mime_type = self.manager.MAGIC.from_file(
                                attachment_path.as_posix()
                            )
                            with open(attachment_path, "rb") as f:
                                payload = f.read()
                                self.ingest_attachment(
                                    entity, attachment_path.name, mime_type, payload
                                )
            except subprocess.CalledProcessError as err:
                raise ProcessingException(f"Cannot extract attachments: {err}") from err
            except Exception as err:
                raise ProcessingException(f"Cannot parse email: {err}") from err
