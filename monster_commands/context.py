"""Shared command types. Kept separate so handlers and the router do not import each other at load time."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


class UsageError(Exception):
    pass


@dataclass(frozen=True)
class Command:
    name: str
    summary: str
    usage: str
    group: str
    handler: Callable[["Ctx"], str]
    aliases: tuple[str, ...] = ()


@dataclass
class Ctx:
    player_id: str
    channel_id: str
    args: list[str]
    command: str


@dataclass
class Reply:
    """Chat result. `text` is the plain fallback. `view` is an embed payload."""
    text: str
    view: dict | None = None
    story: list[str] | None = None
    controls: dict | None = None

    def __str__(self) -> str:
        return self.text


def field(name: str, value: str, *, inline: bool = False) -> dict:
    """One embed box. `inline` places it beside the previous inline boxes, three per row."""
    body = (value or "").strip() or "—"
    return {"name": (name or "—")[:256], "value": body[:1024], "inline": inline}


def separator(title: str, hint: str = "") -> dict:
    """Full-width field that closes the inline row above it and draws a divider box."""
    bar = "━" * 14
    text = bar if not (hint or "").strip() else f"{bar}\n{hint.strip()}"
    return field(f"▣ {title}", text, inline=False)
