# -*- encoding: utf-8 -*-

import binascii
import os


class Preferences:
    defaults = [
        ("session-key", binascii.b2a_hex(os.urandom(24)).decode("utf-8")),
    ]

    def __init__(self, db):
        self.db = db
        for key, value in self.defaults:
            if self.get(key) is None:
                self.set(key, value)

    def _key(self, key):
        return self.db.client.key(self.db.preference_kind, key)

    def get(self, key, default=None):
        entity = self.db.client.get(self._key(key))
        if entity is None:
            return default
        return entity.get("value", default)

    def set(self, key, value):
        entity = self.db.datastore.Entity(self._key(key))
        entity["value"] = value
        self.db.client.put(entity)
