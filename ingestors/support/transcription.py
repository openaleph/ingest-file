import logging

from followthemoney.proxy import EntityProxy
from openaleph_procrastinate import defer
from openaleph_procrastinate.app import make_app

log = logging.getLogger(__name__)
sync_app = make_app(__loader__.name, sync=True)


class TranscriptionSupport:
    """Provides a helper for queuing a transcription task."""

    def transcribe(self, dataset: str, entity: EntityProxy, context: dict):
        with sync_app.open():
            defer.transcribe(sync_app, dataset, [entity], **context)
