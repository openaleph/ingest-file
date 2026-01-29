import logging
import re
import types
from email.utils import getaddresses, parsedate_to_datetime
from typing import List

from banal import ensure_list
from followthemoney.types import registry
from ftmq.store.fragments.utils import safe_fragment
from normality import ascii_text, safe_filename, stringify

from ingestors.support.cache import CacheSupport
from ingestors.support.html import HTMLSupport
from ingestors.support.temp import TempFileSupport

log = logging.getLogger(__name__)


class EmailIdentity(object):
    def __init__(self, manager, name, email):
        """
        Return a Person entity that encodes the name and e-mail of
        an entity found in an e-mail header.

        We want to create a Person entity even if we only have
        a valid name, or a valid e-mail.
        """
        self.email = ascii_text(stringify(email))
        self.name = stringify(name)
        if not self.name:
            self.name = None
        if not registry.email.validate(self.email):
            self.email = None
        # If the value stored in name is a valid e-mail
        # store it in self.email and set self.name to None
        if self.name and registry.email.validate(self.name):
            self.email = self.email or ascii_text(self.name)
            self.name = None

        # This should be using formataddr, but I cannot figure out how
        # to use that without encoding the name.
        self.label = None
        if self.name is not None and self.email is not None:
            self.label = "%s <%s>" % (self.name, self.email)
        elif self.name is None and self.email is not None:
            self.label = self.email
        elif self.email is None and self.name is not None:
            self.label = self.name

        self.entity = None

        if not self.email:
            return

        key = self.email.strip().lower()
        if key is not None:
            fragment = safe_fragment(self.label)
            self.entity = manager.make_entity("Person")
            self.entity.context = {"mutable": False}
            self.entity.make_id(key)
            self.entity.add("name", self.name)
            self.entity.add("email", self.email)
            manager.emit_entity(self.entity, fragment=fragment)


class EmailSupport(TempFileSupport, HTMLSupport, CacheSupport):
    """Extract metadata from email messages."""

    MID_RE = re.compile(r"<([^>]*)>")
    attachments_checksums = set()

    def ingest_attachment(self, entity, name, mime_type, body):
        has_body = body is not None and len(body)
        if stringify(name) is None and not has_body:
            # Hello, Outlook.
            return

        file_name = safe_filename(name, default="attachment")
        file_path = self.make_work_file(file_name)
        with open(file_path, "wb") as fh:
            if isinstance(body, str):
                body = body.encode("utf-8")
            if body is not None:
                fh.write(body)

        checksum = self.manager.store(file_path, mime_type=mime_type)
        file_path.unlink()

        child = self.manager.make_entity("Document", parent=entity)
        child.make_id(name, checksum)
        child.add("contentHash", checksum)
        child.add("fileName", name)
        child.add("mimeType", mime_type)
        self.attachments_checksums.add(checksum)
        self.manager.queue_entity(child)

    def get_header(self, msg, *headers) -> List:
        """
        As seen in real world, we can't rely on the correct parsing
        of header values by the python built-in email module.
        Therefore we additionally check for the raw header values
        if the values contain "; " as a splitter.
        """

        raw_headers = dict(msg._headers)
        values = set()
        for header in headers:
            try:
                for value in ensure_list(msg.get_all(header)):
                    values.add(value)
                for value in ensure_list(raw_headers.get(header)):
                    if "Subject" not in headers:
                        values.update(value.split(";"))
                    else:
                        # do not break the Subject string apart
                        values.add(value)
            except (TypeError, IndexError, AttributeError, ValueError) as exc:
                log.warning("Failed to parse [%s]: %s", header, exc)
        values = [x.strip() for x in values]
        return values

    def get_dates(self, msg, *headers):
        dates = []
        for value in self.get_header(msg, *headers):
            try:
                dates.append(parsedate_to_datetime(value))
            except Exception:
                log.warning("Failed to parse: %s", value)
        return dates

    def get_identities(self, values):
        values = [v for v in ensure_list(values) if v is not None]
        for name, email in getaddresses(values):
            yield EmailIdentity(self.manager, name, email)

    def get_header_identities(self, msg, *headers):
        yield from self.get_identities(self.get_header(msg, *headers))

    def apply_identities(self, entity, identities, eprop=None, lprop=None):
        if isinstance(identities, types.GeneratorType):
            identities = list(identities)
        for identity in ensure_list(identities):
            if eprop is not None:
                entity.add(eprop, identity.entity)
            if lprop is not None:
                entity.add(lprop, identity.label)
            entity.add("namesMentioned", identity.name)
            entity.add("emailMentioned", identity.email)

    def apply_raw(self, msg, entity, lprop, *headers):
        raw_header_values = self.get_header(msg, *headers)
        for raw_value in raw_header_values:
            raw_value = raw_value.replace('"', "")
            entity.add(lprop, raw_value)

    def parse_message_ids(self, values):
        message_ids = []
        for value in ensure_list(values):
            value = stringify(value)
            if value is None:
                continue
            for message_id in self.MID_RE.findall(value):
                message_id = message_id.strip()
                if len(message_id) <= 4:
                    continue
                message_ids.append(message_id)
        return message_ids

    def parse_references(self, references, in_reply_to):
        references = self.parse_message_ids(references)
        if len(references):
            return references[-1]
        in_reply_to = self.parse_message_ids(in_reply_to)
        if len(in_reply_to):
            return in_reply_to[0]

    def resolve_message_ids(self, entity):
        # https://cr.yp.to/immhf/thread.html
        ctx = self.manager.dataset

        for message_id in entity.get("messageId"):
            key = self.cache_key("mid-ent", ctx, message_id)
            self.add_cache_set(key, entity.id)

            rev_key = self.cache_key("ent-mid", ctx, message_id)
            for response_id in self.get_cache_set(rev_key):
                if response_id == entity.id:
                    continue
                email = self.manager.make_entity("Email")
                email.id = response_id
                email.add("inReplyToEmail", entity.id)
                fragment = safe_fragment(message_id)
                self.manager.emit_entity(email, fragment=fragment)

        for message_id in entity.get("inReplyTo"):
            # forward linking: from message ID to entity ID
            key = self.cache_key("mid-ent", ctx, message_id)
            for email_id in self.get_cache_set(key):
                if email_id != entity.id:
                    entity.add("inReplyToEmail", email_id)

            # backward linking: prepare entity ID for message to come
            rev_key = self.cache_key("ent-mid", ctx, message_id)
            self.add_cache_set(rev_key, entity.id)

    def extract_msg_headers(self, entity, msg):
        """Parse E-Mail headers into FtM properties."""
        try:
            entity.add("indexText", msg.values())
        except Exception as ex:
            log.warning("Cannot parse all headers: %r", ex)
        entity.add("subject", self.get_header(msg, "Subject"))
        entity.add("date", self.get_dates(msg, "Date"))
        entity.add("mimeType", self.get_header(msg, "Content-Type"))
        entity.add("threadTopic", self.get_header(msg, "Thread-Topic"))
        entity.add("generator", self.get_header(msg, "X-Mailer"))
        entity.add("language", self.get_header(msg, "Content-Language"))
        entity.add("keywords", self.get_header(msg, "Keywords"))
        entity.add("summary", self.get_header(msg, "Comments"))
        message_id = self.get_header(msg, "Message-ID")
        entity.add("messageId", self.parse_message_ids(message_id))
        references = self.get_header(msg, "References")
        in_reply_to = self.get_header(msg, "In-Reply-To")
        entity.add("inReplyTo", self.parse_references(references, in_reply_to))

        return_path = self.get_header_identities(msg, "Return-Path")
        self.apply_identities(entity, return_path)

        reply_to = self.get_header_identities(msg, "Reply-To")
        self.apply_identities(entity, reply_to)

        sender = self.get_header_identities(msg, "Sender", "X-Sender")
        self.apply_identities(entity, sender, "emitters", "sender")
        self.apply_raw(msg, entity, "sender", "Sender", "X-Sender")

        froms = self.get_header_identities(msg, "From", "X-From")  # codespell:ignore
        self.apply_identities(entity, froms, "emitters", "from")  # codespell:ignore
        self.apply_raw(msg, entity, "from", "From", "X-From")

        tos = self.get_header_identities(msg, "To", "Resent-To")
        self.apply_identities(entity, tos, "recipients", "to")
        self.apply_raw(msg, entity, "to", "To", "Resent-To")

        ccs = self.get_header_identities(msg, "CC", "Cc", "Resent-Cc")
        self.apply_identities(entity, ccs, "recipients", "cc")
        self.apply_raw(msg, entity, "cc", "CC", "Cc", "Resent-Cc")

        bccs = self.get_header_identities(msg, "Bcc", "BCC", "Resent-Bcc")
        self.apply_identities(entity, bccs, "recipients", "bcc")
        self.apply_raw(msg, entity, "bcc", "Bcc", "BCC", "Resent-Bcc")
