# -*- encoding: utf-8 -*-

import time

from configparser import NoOptionError, NoSectionError


class Guard:
    def __init__(self, db):
        self.db = db
        self.conf = db.conf.section("guard")
        try:
            self.max_age = db.conf.getint("general", "max-age")
        except (NoOptionError, NoSectionError):
            self.max_age = None

    def validate(self, uri, comment):
        if not self.conf.getboolean("enabled"):
            return True, ""

        for func in (self._limit, self._spam):
            valid, reason = func(uri, comment)
            if not valid:
                return False, reason
        return True, ""

    def _limit(self, uri, comment):
        comments = self.db.comments._all()
        recent = [
            item for item in comments if item["remote_addr"] == comment["remote_addr"] and time.time() - item["created"] < 60
        ]
        if len(recent) >= self.conf.getint("ratelimit"):
            return False, "{0}: ratelimit exceeded ({1})".format(
                comment["remote_addr"], ", ".join(str(item["id"]) for item in recent)
            )

        if comment["parent"] is None:
            direct = [
                item
                for item in comments
                if item["uri"] == uri and item["remote_addr"] == comment["remote_addr"] and item["parent"] is None
            ]
            if len(direct) >= self.conf.getint("direct-reply"):
                return False, "%i direct responses to %s" % (len(direct), uri)
        elif self.conf.getboolean("reply-to-self") is False:
            replies_to_self = [
                item
                for item in comments
                if item["remote_addr"] == comment["remote_addr"]
                and item["id"] == comment["parent"]
                and time.time() - item["created"] < self.max_age
            ]
            if replies_to_self:
                return False, "edit time frame is still open"

        if self.conf.getboolean("require-email") and not comment.get("email"):
            return False, "email address required but not provided"
        if self.conf.getboolean("require-author") and not comment.get("author"):
            return False, "author address required but not provided"
        return True, ""

    def _spam(self, uri, comment):
        return True, ""
