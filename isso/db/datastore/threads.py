# -*- encoding: utf-8 -*-

import zlib


def Thread(id, uri, title):
    return {"id": id, "uri": uri, "title": title}


class Threads:
    def __init__(self, db):
        self.db = db

    def _key(self, uri):
        return self.db.client.key(self.db.thread_kind, uri)

    @staticmethod
    def id_for_uri(uri):
        return zlib.crc32(uri.encode("utf-8"))

    def __contains__(self, uri):
        if self.db.client.get(self._key(uri)) is not None:
            return True
        return self.db.comments._first_for_uri(uri) is not None

    def __getitem__(self, uri):
        entity = self.db.client.get(self._key(uri))
        if entity is not None:
            return Thread(entity.get("id", self.id_for_uri(uri)), uri, entity.get("title"))
        if self.db.comments._first_for_uri(uri) is not None:
            return Thread(self.id_for_uri(uri), uri, uri)
        raise KeyError(uri)

    def get(self, id):
        query = self.db.client.query(kind=self.db.thread_kind)
        query.add_filter("id", "=", id)
        entity = next(iter(query.fetch(limit=1)), None)
        if entity is None:
            return None
        return Thread(entity.get("id"), entity.get("uri"), entity.get("title"))

    def new(self, uri, title):
        entity = self.db.datastore.Entity(self._key(uri))
        entity.update({"id": self.id_for_uri(uri), "uri": uri, "title": title})
        self.db.client.put(entity)
        return Thread(entity["id"], uri, title)
