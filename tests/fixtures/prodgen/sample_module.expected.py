#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import absolute_import, division, print_function
__metaclass__ = type




import json
import re

_PATTERN = re.compile(r"#[0-9a-f]{6}")


class Collector(object):

    def empty(self):
        pass

    def run(self, data):
        text = "# not a comment"
        return json.dumps({"text": text, "match": bool(_PATTERN.search(data))})


def main():
    return Collector().run("#abcdef")


if __name__ == "__main__":
    main()
