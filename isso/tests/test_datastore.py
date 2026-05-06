# -*- encoding: utf-8 -*-

from isso.db.datastore.comments import Comments


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
