"""
Collection rules for this suite.

The checkout lives in iCloud Drive, which resolves a sync conflict by writing a
second copy beside the original — `route_table 2.py` next to `route_table.py`.
pytest happily collects those. It happened while this suite was being worked on:
two duplicates appeared, the run reported 1122 tests where CI reported 1116, and
the six extra passes were a shadow copy of a file that already ran. They were
byte-identical that time, so nothing was wrong — which is the problem. A stale
copy of an *older* revision would have gone on asserting the old behaviour, in
green, under a filename nobody greps for.

Those files are never tracked, so the fix is not `.gitignore` — git should keep
showing them so they get deleted. pytest is what must not run them.
"""

#: Matches the ` 2.py`, ` 3.py` … suffix iCloud appends to a conflicted copy.
#: Deliberately narrow: a legitimate module would not be named this way, and a
#: broader glob risks silently skipping real tests, which is the failure mode
#: this whole area already had once.
collect_ignore_glob = ["* [0-9].py", "* [0-9][0-9].py"]
