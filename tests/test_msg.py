# -*- coding: utf-8 -*-
from pprint import pprint  # noqa

from openaleph_procrastinate import defer

from ingestors.tasks import app
from tests.support import TestCase

ATTACHMENT_NAME = "7b2fd116582e4b66be0451b4755fff1d.png"


class RFC822Test(TestCase):
    def test_thunderbird(self):
        fixture_path, entity = self.fixture("testThunderbirdEml.eml")
        self.manager.ingest(fixture_path, entity)
        self.assertSuccess(entity)
        pprint(entity.to_dict())
        self.assertEqual(entity.first("subject"), "JUnit test message")
        self.assertIn("Dear Vladimir", entity.first("bodyText"))

    def test_naumann(self):
        fixture_path, entity = self.fixture("fnf.msg")
        self.manager.ingest(fixture_path, entity)
        self.assertSuccess(entity)
        self.assertIn("Innovationskongress", entity.first("subject"))
        self.assertIn("freiheit.org", entity.first("bodyHtml"))
        self.assertEqual(entity.schema.name, "Email")

    def test_mbox(self):
        fixture_path, entity = self.fixture("plan.mbox")
        self.manager.ingest(fixture_path, entity)
        self.assertSuccess(entity)
        self.assertEqual(entity.schema.name, "Package")

    def test_base64(self):
        fixture_path, entity = self.fixture("email_base64.eml")
        self.manager.ingest(fixture_path, entity)
        self.assertSuccess(entity)
        self.assertEqual(entity.schema.name, "Email")
        self.assertEqual(entity.get("bodyText"), ["Base64 email payload"])

    def test_multipart_alternative(self):
        fixture_path, entity = self.fixture("email_multipart_alternative.eml")
        self.manager.ingest(fixture_path, entity)
        self.assertSuccess(entity)
        self.assertEqual(entity.schema.name, "Email")
        self.assertEqual(
            entity.get("bodyText"), ["This is a **multipart/alternative** message."]
        )
        self.assertEqual(
            entity.get("bodyHtml"),
            ["This is a <strong>multipart/alternative</strong> message."],
        )

    def test_multipart_mixed(self):
        fixture_path, entity = self.fixture("email_multipart_mixed.eml")
        self.manager.ingest(fixture_path, entity)
        self.assertSuccess(entity)
        self.assertEqual(entity.schema.name, "Email")
        self.assertEqual(
            entity.get("bodyText"),
            [
                "This is the first part (plaintext)",
                "This is the second part (HTML)",
                "This is the third part (plaintext)",
                "This is the fourth part (HTML)",
            ],
        )
        self.assertEqual(
            entity.get("bodyHtml"),
            [
                "This is the first part (plaintext)",
                "This is the second part (HTML)",
                "This is the third part (plaintext)",
                "This is the fourth part (HTML)",
            ],
        )

    def test_multipart_nested(self):
        fixture_path, entity = self.fixture("email_multipart_nested.eml")
        self.manager.ingest(fixture_path, entity)
        self.assertSuccess(entity)
        self.assertEqual(entity.schema.name, "Email")
        self.assertEqual(
            entity.get("bodyText"),
            [
                "This is the **first** part",
                "This is the second part",
            ],
        )
        self.assertEqual(
            entity.get("bodyHtml"),
            [
                "This is the <strong>first</strong> part",
                "This is the second part",
            ],
        )

    def test_plaintext_encode_markup(self):
        fixture_path, entity = self.fixture("email_encode_markup.eml")
        self.manager.ingest(fixture_path, entity)
        self.assertSuccess(entity)
        self.assertEqual(entity.schema.name, "Email")
        self.assertEqual(
            entity.get("bodyText"),
            [
                "This is the body of a plaintext message.\n\nEven though it's plaintext, it contains some <strong>HTML markup</strong>.",
            ],
        )
        self.assertEqual(
            entity.get("bodyHtml"),
            [
                "This is the body of a plaintext message.<br><br>Even though it&#x27;s plaintext, it contains some &lt;strong&gt;HTML markup&lt;/strong&gt;.",
            ],
        )

    def test_html_strip_markup(self):
        fixture_path, entity = self.fixture("email_strip_markup.eml")
        self.manager.ingest(fixture_path, entity)
        self.assertSuccess(entity)
        self.assertEqual(entity.schema.name, "Email")
        self.assertEqual(
            entity.get("bodyText"),
            [
                "This is the body of an HTML message.",
            ],
        )
        self.assertEqual(
            entity.get("bodyHtml"),
            [
                "This is the body of an <strong>HTML</strong> message.",
            ],
        )
        self.assertNotIn(
            "This is the body of an HTML message.", entity.get("indexText")
        )

    def test_attached_email(self):
        fixture_path, entity = self.fixture("email_attached_plaintext.eml")
        self.manager.ingest(fixture_path, entity)
        self.assertSuccess(entity)
        self.assertEqual(
            entity.get("bodyText"),
            ["This is the body of the email that contains the attachment."],
        )

        fixture_path, entity = self.fixture("email_attached_alternative.eml")
        self.manager.ingest(fixture_path, entity)
        self.assertSuccess(entity)
        self.assertEqual(
            entity.get("bodyText"),
            ["This is the body of the email that contains the attachment."],
        )

    def test_attached_inline_email(self):
        fixture_path, entity = self.fixture("email_attached_inline.eml")
        self.manager.ingest(fixture_path, entity)
        self.assertSuccess(entity)
        self.assertEqual(
            entity.get("bodyText"),
            [
                "This is the body of the email that contains the attachment.",
                "From: john.doe@example.org\nTo: jane.doe@example.org\nSubject: Plaintext only",
                "This is the body of a plaintext message.",
            ],
        )
        self.assertEqual(
            entity.get("bodyHtml"),
            [
                "This is the body of the email that contains the attachment.",
                "From: john.doe@example.org<br>To: jane.doe@example.org<br>Subject: Plaintext only",
                "This is the body of a plaintext message.",
            ],
        )


class AttachmentFanoutTest(TestCase):
    """`RFC822Ingestor` walks the mime tree and then sweeps the same message
    with ripmime to catch what a broken message hides from the parser. Both
    passes queue what they find, so the sweep has to recognise the attachments
    the walk already handled – otherwise every message queues its attachments
    twice, and since an attached message is queued as a child and swept again,
    that doubling compounds with every level of nesting."""

    def queued(self) -> list[dict]:
        """The entities queued for ingestion, straight off the connector."""
        return [
            entity
            for job in app.connector.jobs.values()
            if job["queue_name"] == defer.tasks.ingest.queue
            for entity in job["args"]["payload"]["entities"]
        ]

    def test_attachment_queued_once(self):
        """The sweep hashes the file it extracted to compare it against the
        attachments already ingested. Comparing that against the *archive*
        checksum instead never matches on the lakehouse, which hashes sha256
        where the legacy archive hashes sha1."""
        fixture_path, entity = self.fixture("fnf.msg")
        self.manager.ingest(fixture_path, entity)
        self.assertSuccess(entity)

        queued = self.queued()
        self.assertEqual(len(queued), 1, [e["id"] for e in queued])
        self.assertEqual(queued[0]["properties"]["fileName"], [ATTACHMENT_NAME])

    def test_nested_message_not_flattened(self):
        """An unbounded ripmime sweep hands back the whole tree, so the inner
        image would be queued here as well as under the message it belongs to.
        Only the direct attachment may be queued."""
        fixture_path, entity = self.fixture("email_nested_attachment.eml")
        self.manager.ingest(fixture_path, entity)
        self.assertSuccess(entity)

        queued = self.queued()
        self.assertEqual(len(queued), 1, [e["id"] for e in queued])
        self.assertEqual(queued[0]["properties"]["fileName"], ["inner.eml"])
