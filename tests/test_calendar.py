# -*- coding: utf-8 -*-

from ingestors.support.email import EmailIdentity, EmailSupport
from tests.support import TestCase


class CalendarIngestorTest(TestCase):
    def test_match(self):
        fixture_path, entity = self.fixture("meetup.ics")
        self.manager.ingest(fixture_path, entity)
        entities = self.get_emitted()
        assert len(entities) == 5, entities
        schemata = [e.schema.name for e in entities]
        assert "Person" in schemata, entities
        assert "Event" in schemata, entities
        assert "PlainText" in schemata, entities

    def test_event_without_addresses(self):
        """`event.ical` carries neither ORGANIZER nor ATTENDEE, so
        `address_entity` builds an `EmailIdentity` with no usable address. It
        used to raise `AttributeError` there, which `ingest` re-raised as
        "Failed to parse iCalendar" – failing the job, and with it every
        retry of whatever container queued the file."""
        fixture_path, entity = self.fixture("event.ical")
        self.manager.ingest(fixture_path, entity)
        self.assertSuccess(entity)
        entities = self.get_emitted()
        schemata = [e.schema.name for e in entities]
        assert "Event" in schemata, entities
        # no address in the file, so no Person is invented for one
        assert "Person" not in schemata, entities
        events = [e for e in entities if e.schema.name == "Event"]
        assert events[0].first("name") == "Abraham Lincoln", events
        assert not events[0].get("organizer"), events


class EmailIdentityTest(TestCase):
    def test_identity_without_usable_address(self):
        """An identity built from nothing at all is still a well-formed
        object – `label` and `entity` are what callers reach for."""
        identity = EmailIdentity(self.manager, None, None)
        assert identity.email is None, identity
        assert identity.name is None, identity
        assert identity.label is None, identity
        assert identity.entity is None, identity
        assert self.manager.entities == [], self.manager.entities

    def test_identity_with_name_only(self):
        """A name without an address emits no Person either, and
        `apply_identities` skips it the way it always has."""
        identity = EmailIdentity(self.manager, "Jane Doe", "not-an-email")
        assert identity.entity is None, identity
        email = self.manager.make_entity("Email")
        email.id = "identity-name-only"
        EmailSupport().apply_identities(email, [identity], "emitters", "from")
        assert not email.get("emitters"), email.to_dict()
        assert not email.get("namesMentioned"), email.to_dict()

    def test_identity_with_address(self):
        identity = EmailIdentity(self.manager, "Jane Doe", "Jane@Example.COM")
        assert identity.email == "jane@example.com", identity
        assert identity.label == "Jane Doe <jane@example.com>", identity
        assert identity.entity is not None, identity
        assert identity.entity.schema.name == "Person", identity.entity
