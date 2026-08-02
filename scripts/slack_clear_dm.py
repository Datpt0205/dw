"""Delete Ngọc's (the bot's) own messages in the demo DMs — visual cleanup.

Slack API only lets a bot delete ITS OWN messages: An/Bình/Chi's messages
remain (they can delete manually if wanted). This is cosmetic only — Ngọc's
actual memory is the slot state in Postgres; wipe that with
``bash scripts/demo_reset.sh``.

Usage (repo root, .env present):  uv run python scripts/slack_clear_dm.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

API = "https://slack.com/api"


def _env() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def _call(client: httpx.Client, method: str, **params: object) -> dict:
    response = client.post(f"{API}/{method}", data=params)
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise SystemExit(f"Slack {method} failed: {data.get('error')}")
    return data


def main() -> None:
    # Windows console defaults to cp1252 which cannot print Vietnamese.
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    env = _env()
    token = env.get("SLACK_BOT_TOKEN", "")
    if not token.startswith("xoxb-"):
        raise SystemExit("SLACK_BOT_TOKEN missing in .env")
    user_ids = [
        env[key]
        for key in ("SLACK_USER_AN_ID", "SLACK_USER_BINH_ID", "SLACK_USER_CHI_ID")
        if env.get(key)
    ]
    if not user_ids:
        raise SystemExit("No SLACK_USER_*_ID configured in .env")

    with httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=30) as client:
        deleted = 0
        for user_id in user_ids:
            channel = _call(client, "conversations.open", users=user_id)["channel"]["id"]
            cursor = ""
            while True:
                history = _call(
                    client,
                    "conversations.history",
                    channel=channel,
                    limit=200,
                    **({"cursor": cursor} if cursor else {}),
                )
                for message in history.get("messages", []):
                    # Only the bot's own messages are deletable by the bot.
                    if not message.get("bot_id"):
                        continue
                    try:
                        _call(client, "chat.delete", channel=channel, ts=message["ts"])
                        deleted += 1
                        time.sleep(0.4)  # stay under Slack rate limits
                    except SystemExit as exc:  # cant_delete_message etc. — skip
                        print(f"  skip {message['ts']}: {exc}", file=sys.stderr)
                cursor = history.get("response_metadata", {}).get("next_cursor", "")
                if not cursor:
                    break
            print(f"DM {user_id}: dọn xong.")
    print(
        f"✔ Đã xóa {deleted} tin nhắn của Ngọc. "
        "Tin của người dùng phải tự xóa tay (giới hạn Slack)."
    )


if __name__ == "__main__":
    main()
