#!/usr/bin/python
# -*- coding: utf-8 -*-
# sample_module.py — prodgen golden fixture (python_kind=library)
"""Module docstring is removed for library modules."""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: sample
short_description: dropped for library modules
'''

EXAMPLES = r'''
- sample:
    host: 1.2.3.4
'''

RETURN = r'''
ok:
  description: dropped
'''

import json  # noqa: E402
import re    # type: ignore

_PATTERN = re.compile(r"#[0-9a-f]{6}")   # a '#' inside a string literal stays


class Collector(object):
    """Class docstring removed."""

    def empty(self):
        """Only a docstring: the body becomes `pass`."""

    def run(self, data):
        """Method docstring removed; comments too."""
        # pragma: no cover — tool directive, removable
        text = "# not a comment"  # nosec rule12-r1
        return json.dumps({"text": text, "match": bool(_PATTERN.search(data))})


def main():
    # the body keeps working without its explanations
    return Collector().run("#abcdef")


if __name__ == "__main__":
    main()
