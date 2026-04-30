# -*- encoding: utf-8 -*-

from configparser import NoOptionError, NoSectionError

from isso.db.datastore.comments import Comments
from isso.db.datastore.preferences import Preferences
from isso.db.datastore.spam import Guard
from isso.db.datastore.threads import Threads


def get_config(section, key, default=None):
    try:
        return section.get(key)
    except (NoOptionError, NoSectionError):
        return default


class Datastore:
    """Google Cloud Datastore backend.

    The Kotlin Ossi implementation stores comments in a single Datastore kind.
    This backend keeps that shape for comments so an existing Ossi Datastore DB
    remains readable, and adds small sibling kinds for Isso thread metadata and
    preferences.
    """

    def __init__(self, conf):
        try:
            from google.cloud import datastore
        except ImportError as exc:
            raise RuntimeError(
                "The Datastore backend requires google-cloud-datastore. "
                "Install it with `pip install isso[datastore]`."
            ) from exc

        section = conf.section("datastore")
        project = get_config(section, "project") or None
        database = get_config(section, "database") or None
        namespace = get_config(section, "namespace") or None

        kwargs = {}
        if project:
            kwargs["project"] = project
        if namespace:
            kwargs["namespace"] = namespace
        if database:
            kwargs["database"] = database

        self.conf = conf
        self.datastore = datastore
        self.client = datastore.Client(**kwargs)
        self.kind = get_config(section, "kind", "comments")
        self.thread_kind = get_config(section, "thread-kind", f"{self.kind}_threads")
        self.preference_kind = get_config(section, "preference-kind", f"{self.kind}_preferences")

        self.preferences = Preferences(self)
        self.threads = Threads(self)
        self.comments = Comments(self)
        self.guard = Guard(self)
