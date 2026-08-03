"""Conversational (chat front-office) intake for DW01.

The Slack/chat layer is a *presentation channel*: it collects a procurement
request through dialogue, then drives the exact same application commands the
web UI uses. Slack is never the source of truth and never an authorization
authority (blueprint + conversation-first plan §3.1).
"""
