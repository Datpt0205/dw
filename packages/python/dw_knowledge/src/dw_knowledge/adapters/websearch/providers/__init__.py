"""One module per search engine. Each maps its own dialect onto ``SearchHit``.

A provider does exactly three things: build the request its API wants, turn the
response into hits, and classify its own failures. It never decides whether a
failure is worth trying someone else for — that judgement belongs to the chain,
which is the only place that knows who else there is.
"""

from __future__ import annotations
