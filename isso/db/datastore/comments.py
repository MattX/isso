# -*- encoding: utf-8 -*-

import base64
import logging
import time

from collections import Counter

from isso.db.datastore.threads import Threads
from isso.utils import Bloomfilter


logger = logging.getLogger("isso")

MAX_LIKES_AND_DISLIKES = 142


class Comments:
    fields = [
        "tid",
        "id",
        "parent",
        "created",
        "modified",
        "mode",
        "remote_addr",
        "text",
        "author",
        "email",
        "website",
        "likes",
        "dislikes",
        "voters",
        "notification",
    ]

    def __init__(self, db):
        self.db = db

    def _key(self, id=None):
        if id is None:
            return self.db.client.key(self.db.kind)
        return self.db.client.key(self.db.kind, int(id))

    def _query(self):
        return self.db.client.query(kind=self.db.kind)

    def _first_for_uri(self, uri):
        query = self._query()
        query.add_filter("uri", "=", uri)
        return next(iter(query.fetch(limit=1)), None)

    def _all(self):
        return [self._comment(entity) for entity in self._query().fetch()]

    def _by_uri(self, uri):
        query = self._query()
        query.add_filter("uri", "=", uri)
        return [self._comment(entity) for entity in query.fetch()]

    @staticmethod
    def _mode_visible(mode, item_mode):
        mode = int(mode)
        item_mode = int(item_mode or 1)
        return (mode | item_mode) == mode

    @staticmethod
    def _voters(value):
        if value is None:
            return Bloomfilter().array
        if isinstance(value, str):
            return bytearray(base64.b64decode(value))
        return bytearray(value)

    @staticmethod
    def _voters_for_store(value):
        return base64.b64encode(bytes(value)).decode("ascii")

    def _comment(self, entity):
        uri = entity.get("uri")
        remote_addr = entity.get("remote_addr") or entity.get("hash") or "127.0.0.0"
        return {
            "tid": entity.get("tid") or Threads.id_for_uri(uri or ""),
            "id": entity.key.id,
            "parent": entity.get("parent"),
            "created": float(entity.get("created") or 0),
            "modified": entity.get("modified"),
            "mode": int(entity.get("mode") or 1),
            "remote_addr": remote_addr,
            "text": entity.get("text") or "",
            "author": entity.get("author"),
            "email": entity.get("email"),
            "website": entity.get("website"),
            "likes": int(entity.get("likes") or 0),
            "dislikes": int(entity.get("dislikes") or 0),
            "voters": self._voters(entity.get("voters")),
            "notification": int(entity.get("notification") or 0),
            "uri": uri,
            "title": entity.get("title") or uri,
        }

    def _put_comment(self, entity, comment):
        entity.update(
            {
                "uri": comment.get("uri"),
                "tid": comment.get("tid") or Threads.id_for_uri(comment.get("uri") or ""),
                "parent": comment.get("parent"),
                "created": comment.get("created") or time.time(),
                "modified": comment.get("modified"),
                "mode": int(comment.get("mode") or 1),
                "remote_addr": comment.get("remote_addr"),
                "text": comment.get("text") or "",
                "author": comment.get("author"),
                "email": comment.get("email"),
                "website": comment.get("website"),
                "likes": int(comment.get("likes") or 0),
                "dislikes": int(comment.get("dislikes") or 0),
                "voters": self._voters_for_store(comment.get("voters") or Bloomfilter().array),
                "notification": int(comment.get("notification") or 0),
                "title": comment.get("title") or comment.get("uri"),
            }
        )
        entity.exclude_from_indexes = ("text", "voters")

    def add(self, uri, c):
        def _find(parent):
            if parent in ["0", 0, None]:
                return None
            obj = self.get(parent)
            if obj is None or obj.get("uri") != uri:
                return None
            return _find(obj.get("parent")) or parent

        if c.get("parent") is not None:
            c["parent"] = _find(c["parent"])

        comment = dict(c)
        comment["uri"] = uri
        comment["tid"] = Threads.id_for_uri(uri)
        comment["created"] = comment.get("created") or time.time()
        comment["modified"] = None
        comment["likes"] = 0
        comment["dislikes"] = 0
        comment["voters"] = Bloomfilter(iterable=[comment["remote_addr"]]).array

        key = self.db.client.allocate_ids(self._key(), 1)[0]
        transaction = self.db.client.transaction()
        with transaction:
            entity = self.db.datastore.Entity(key, exclude_from_indexes=("text", "voters"))
            self._put_comment(entity, comment)
            transaction.put(entity)
        return self._comment(entity)

    def activate(self, id):
        entity = self.db.client.get(self._key(id))
        if entity is not None and int(entity.get("mode") or 1) == 2:
            entity["mode"] = 1
            self.db.client.put(entity)

    def is_previously_approved_author(self, email):
        if email is None:
            return False
        cutoff = time.time() - (60 * 60 * 24 * 183)
        for comment in self._all():
            if comment["email"] == email and comment["mode"] == 1 and comment["created"] > cutoff:
                return True
        return False

    def unsubscribe(self, email, id):
        for comment in self._all():
            if comment["email"] == email and (comment["id"] == id or comment.get("parent") == id):
                entity = self.db.client.get(self._key(comment["id"]))
                entity["notification"] = 0
                self.db.client.put(entity)

    def update(self, id, data):
        entity = self.db.client.get(self._key(id))
        if entity is None:
            return None
        for key, value in data.items():
            entity[key] = value
        self.db.client.put(entity)
        return self.get(id)

    def get(self, id):
        entity = self.db.client.get(self._key(id))
        if entity is None:
            return None
        return self._comment(entity)

    def count_modes(self):
        counts = Counter(comment["mode"] for comment in self._all())
        return dict(counts)

    def fetchall(
        self, mode=5, after=0, parent="any", order_by="id", limit=100, page=0, asc=1, comment_id=None, thread_uri=None
    ):
        comments = self._all()
        if comment_id:
            comments = [comment for comment in comments if comment["id"] == comment_id]
        elif thread_uri:
            comments = [comment for comment in comments if comment["uri"] == thread_uri]
        else:
            comments = [comment for comment in comments if comment["mode"] == int(mode)]

        if parent != "any":
            comments = [comment for comment in comments if comment["parent"] == parent]

        comments = self._sort(comments, order_by, asc)
        if limit:
            comments = comments[page * limit : page * limit + limit]
        yield from comments

    def fetch(self, uri, mode=5, after=0, parent="any", order_by="id", asc=1, limit=None, offset=0):
        comments = [
            comment
            for comment in self._by_uri(uri)
            if self._mode_visible(mode, comment["mode"]) and comment["created"] > float(after)
        ]

        if parent != "any":
            comments = [comment for comment in comments if comment["parent"] == parent]

        comments = self._sort(comments, order_by, asc)
        if offset:
            comments = comments[offset:]
        if limit:
            comments = comments[:limit]
        yield from comments

    @staticmethod
    def _sort(comments, order_by, asc):
        allowed = {"id", "created", "modified", "likes", "dislikes", "tid", "karma"}
        if order_by not in allowed:
            order_by = "created"

        def value(comment):
            if order_by == "karma":
                rv = comment["likes"] - comment["dislikes"]
            else:
                rv = comment.get(order_by)
            return (comment["parent"] is not None, rv is None, rv, comment["created"])

        return sorted(comments, key=value, reverse=not bool(asc))

    def _remove_stale(self):
        stale = True
        while stale:
            comments = self._all()
            parents = {comment["parent"] for comment in comments if comment["parent"] is not None}
            stale_ids = [comment["id"] for comment in comments if comment["mode"] == 4 and comment["id"] not in parents]
            stale = bool(stale_ids)
            for id in stale_ids:
                self.db.client.delete(self._key(id))

    def delete(self, id):
        refs = [comment for comment in self._all() if comment["parent"] == id]
        entity = self.db.client.get(self._key(id))
        if entity is None:
            return None

        if not refs:
            self.db.client.delete(self._key(id))
            self._remove_stale()
            return None

        entity["text"] = ""
        entity["mode"] = 4
        entity["author"] = None
        entity["website"] = None
        self.db.client.put(entity)
        self._remove_stale()
        return self.get(id)

    def vote(self, upvote, id, remote_addr):
        transaction = self.db.client.transaction()
        with transaction:
            entity = transaction.get(self._key(id))
            if entity is None:
                return None

            likes = int(entity.get("likes") or 0)
            dislikes = int(entity.get("dislikes") or 0)
            if likes + dislikes >= MAX_LIKES_AND_DISLIKES:
                operation_name = "Upvote" if upvote else "Downvote"
                message = '{} denied due to a "likes + dislikes" total too high ({} >= {})'.format(
                    operation_name, likes + dislikes, MAX_LIKES_AND_DISLIKES
                )
                logger.debug("DatastoreComments.vote(id=%s): %s", id, message)
                return {"likes": likes, "dislikes": dislikes, "message": message}

            bf = Bloomfilter(self._voters(entity.get("voters")), likes + dislikes)
            if remote_addr in bf:
                operation_name = "Upvote" if upvote else "Downvote"
                message = "{} denied because a vote has already been registered for this remote address: {}".format(
                    operation_name, remote_addr
                )
                logger.debug("DatastoreComments.vote(id=%s): %s", id, message)
                return {"likes": likes, "dislikes": dislikes, "message": message}

            bf.add(remote_addr)
            if upvote:
                likes += 1
                entity["likes"] = likes
            else:
                dislikes += 1
                entity["dislikes"] = dislikes
            entity["voters"] = self._voters_for_store(bf.array)
            entity.exclude_from_indexes = ("text", "voters")
            transaction.put(entity)
            return {"likes": likes, "dislikes": dislikes}

    def reply_count(self, url, mode=5):
        counts = Counter()
        for comment in self._by_uri(url):
            if self._mode_visible(mode, comment["mode"]):
                counts[comment["parent"]] += 1
        return dict(counts)

    def count(self, *urls):
        counts = Counter()
        for comment in self._all():
            if comment["mode"] == 1:
                counts[comment["uri"]] += 1
        return [counts.get(url, 0) for url in urls]

    def purge(self, delta):
        now = time.time()
        for comment in self._all():
            if comment["mode"] == 2 and now - comment["created"] > delta:
                self.db.client.delete(self._key(comment["id"]))
        self._remove_stale()
