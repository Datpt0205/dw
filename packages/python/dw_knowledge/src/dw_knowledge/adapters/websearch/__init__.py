"""Generic web search plumbing: find pages, fetch them, remember the answer.

Nothing in here knows about law. It knows how to ask a search engine, how to
turn a URL into readable text, and how to avoid asking twice. What counts as a
trustworthy source, which passage is worth keeping, and how a passage becomes
evidence all live one level up, in ``adapters/web_law_search.py``.

That line matters because a second consumer is coming: the same fetch-and-cache
stack serves any live-source retrieval, and a provider adapter that had to
import a legal-source config to make an HTTP call would make that impossible.
"""

from __future__ import annotations
