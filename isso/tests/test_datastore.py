# -*- encoding: utf-8 -*-

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from isso import config
from isso.db.datastore import Datastore
from isso.db.datastore.comments import MAX_LIKES_AND_DISLIKES, Comments
from isso.db.datastore.preferences import Preferences
from isso.db.datastore.threads import Threads
from isso.utils import Bloomfilter


def comment(id, created, parent=None, likes=0, modified=None):
    return {
        "id": id,
        "parent": parent,
        "created": created,
        "modified": modified,
        "likes": likes,
        "dislikes": 0,
        "tid": 1,
    }


@pytest.fixture
def backend():
    google_datastore = pytest.importorskip("google.cloud.datastore")
    client = MagicMock()

    def key(kind, id=None):
        if id is None:
            return google_datastore.Key(kind, project="test-project")
        return google_datastore.Key(kind, id, project="test-project")

    client.key.side_effect = key
    db = SimpleNamespace(
        client=client,
        datastore=google_datastore,
        kind="comments",
        thread_kind="comment_threads",
        preference_kind="comment_preferences",
    )
    db.comments = Comments(db)
    return db


def entity(backend, id, **values):
    rv = backend.datastore.Entity(backend.client.key(backend.kind, id))
    rv.update(values)
    return rv


def test_datastore_initializes_google_client_and_components(monkeypatch):
    google_datastore = pytest.importorskip("google.cloud.datastore")
    client = MagicMock()
    client.get.return_value = {"value": "existing-session-key"}
    client.key.side_effect = lambda kind, id=None: google_datastore.Key(kind, id, project="test-project")
    monkeypatch.setattr(google_datastore, "Client", MagicMock(return_value=client))
    conf = config.new(
        {
            "datastore": {
                "project": "test-project",
                "database": "comments-db",
                "namespace": "production",
                "kind": "posts",
            },
            "general": {},
            "guard": {"enabled": "false"},
        }
    )

    db = Datastore(conf)

    google_datastore.Client.assert_called_once_with(project="test-project", database="comments-db", namespace="production")
    assert db.kind == "posts"
    assert db.thread_kind == "posts_threads"
    assert db.preference_kind == "posts_preferences"
    assert db.preferences.get("session-key") == "existing-session-key"


def test_comment_entity_mapping_handles_legacy_shape(backend):
    stored = entity(
        backend,
        7,
        uri="/post",
        hash="legacy-hash",
        voters="YWJj",
        created=3,
        likes=2,
        text="hello",
    )

    mapped = backend.comments._comment(stored)

    assert mapped["id"] == 7
    assert mapped["tid"] == Threads.id_for_uri("/post")
    assert mapped["remote_addr"] == "legacy-hash"
    assert mapped["voters"] == bytearray(b"abc")
    assert mapped["title"] == "/post"
    assert Comments._voters(None) == Bloomfilter().array
    assert Comments._voters(b"abc") == bytearray(b"abc")


def test_add_builds_an_entity_and_flattens_nested_replies(backend):
    root = {"id": 3, "parent": None, "uri": "/post"}
    backend.comments.get = MagicMock(return_value=root)
    allocated_key = backend.client.key(backend.kind, 8)
    backend.client.allocate_ids.return_value = [allocated_key]
    transaction = backend.client.transaction.return_value
    transaction.__enter__.return_value = transaction
    values = {
        "parent": 3,
        "created": 10,
        "mode": 1,
        "remote_addr": "192.0.2.1",
        "text": "reply",
    }

    added = backend.comments.add("/post", values)

    assert added["id"] == 8
    assert added["parent"] == 3
    assert added["tid"] == Threads.id_for_uri("/post")
    stored = transaction.put.call_args.args[0]
    assert stored["uri"] == "/post"
    assert stored["likes"] == 0
    assert stored.exclude_from_indexes == ("text", "voters")


def test_fetch_and_counts_use_mapped_entities(backend):
    query = backend.client.query.return_value
    query.fetch.return_value = [
        entity(backend, 1, uri="/post", created=10, mode=1, parent=None, likes=2),
        entity(backend, 2, uri="/post", created=20, mode=2, parent=1),
    ]

    visible = list(backend.comments.fetch("/post", mode=5, after=0, order_by="karma", asc=0, limit=1))
    all_pending = list(backend.comments.fetchall(mode=2))

    assert [item["id"] for item in visible] == [1]
    assert [item["id"] for item in all_pending] == [2]
    assert backend.comments.count_modes() == {1: 1, 2: 1}
    assert backend.comments.reply_count("/post") == {None: 1}
    assert backend.comments.count("/post", "/missing") == [1, 0]


def test_update_activate_and_unsubscribe(backend):
    stored = entity(backend, 4, uri="/post", created=10, mode=2, email="a@example.com", notification=1)
    backend.client.get.return_value = stored
    backend.comments._all = MagicMock(return_value=[backend.comments._comment(stored) | {"parent": None}])

    backend.comments.activate(4)
    updated = backend.comments.update(4, {"text": "updated"})
    backend.comments.unsubscribe("a@example.com", 4)

    assert updated["mode"] == 1
    assert updated["text"] == "updated"
    assert stored["notification"] == 0
    assert backend.client.put.call_count == 3


def test_vote_rejects_duplicates_and_excessive_totals(backend):
    stored = entity(
        backend,
        5,
        uri="/post",
        created=10,
        mode=1,
        voters=Comments._voters_for_store(Bloomfilter().array),
    )
    transaction = backend.client.transaction.return_value
    transaction.__enter__.return_value = transaction
    transaction.get.return_value = stored

    assert backend.comments.vote(True, 5, "198.51.100.1") == {"likes": 1, "dislikes": 0}
    duplicate = backend.comments.vote(False, 5, "198.51.100.1")
    assert "already been registered" in duplicate["message"]

    stored.update({"likes": MAX_LIKES_AND_DISLIKES, "dislikes": 0})
    denied = backend.comments.vote(False, 5, "198.51.100.2")
    assert "total too high" in denied["message"]

    transaction.get.return_value = None
    assert backend.comments.vote(True, 999, "198.51.100.1") is None


def test_threads_and_preferences_delegate_to_the_client(backend):
    preferences = Preferences(backend)
    preferences.set("theme", "dark")
    preference = backend.client.put.call_args.args[0]
    backend.client.get.return_value = preference
    assert preferences.get("theme") == "dark"

    backend.client.get.return_value = None
    threads = Threads(backend)
    backend.comments._first_for_uri = MagicMock(return_value={"uri": "/legacy"})
    assert "/legacy" in threads
    assert threads["/legacy"]["title"] == "/legacy"

    created = threads.new("/native", "Native")
    query = backend.client.query.return_value
    query.fetch.return_value = [backend.client.put.call_args.args[0]]
    assert threads.get(created["id"]) == created


def test_sort_newest_top_level_comments_descending():
    comments = [comment(1, 1), comment(2, 2), comment(3, 3)]

    rv = Comments._sort(comments, "created", asc=0)

    assert [item["id"] for item in rv] == [3, 2, 1]


def test_sort_nested_comments_stays_oldest_first():
    comments = [comment(1, 1), comment(2, 2, parent=1), comment(3, 3, parent=1)]

    rv = Comments._sort(comments, "created", asc=0)

    assert [item["id"] for item in rv] == [1, 2, 3]


def test_sort_modified_desc_keeps_unmodified_last():
    comments = [comment(1, 1, modified=None), comment(2, 2, modified=10), comment(3, 3, modified=20)]

    rv = Comments._sort(comments, "modified", asc=0)

    assert [item["id"] for item in rv] == [3, 2, 1]
