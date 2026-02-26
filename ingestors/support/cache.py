import logging
from functools import cached_property

from banal import ensure_list
from servicelayer.cache import get_redis, make_key
from servicelayer.settings import REDIS_LONG
from servicelayer.tags import Tags

from ingestors.settings import Settings

log = logging.getLogger(__name__)


class CacheSupport(object):
    @cached_property
    def conn(self):
        return get_redis()

    @cached_property
    def tags(self):
        return Tags("ingest_cache", uri=Settings().tags_database_uri)

    def cache_key(self, *parts):
        return make_key(*parts)

    def get_cache_set(self, key):
        return ensure_list(self.conn.smembers(key))

    def add_cache_set(self, key, value):
        self.conn.sadd(key, value)
        self.conn.expire(key, REDIS_LONG)
