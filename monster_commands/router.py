"""Parse a command line and run the matching game handler."""
from __future__ import annotations

import shlex
from typing import Optional

from .context import Command, Ctx, Reply, UsageError
from .present import coerce


def _specs() -> list[Command]:
    from . import handlers
    return list(handlers.COMMANDS)


def list_commands() -> list[Command]:
    return _specs()


def _index() -> dict[str, Command]:
    table: dict[str, Command] = {}
    for spec in _specs():
        table[spec.name] = spec
        for alias in spec.aliases:
            table[alias] = spec
    return table


def help_text(group: Optional[str] = None) -> str:
    lines = [
        "MonSTER — lệnh (prefix `!` hoặc slash cùng tên)",
        "Ví dụ: `!go 1`, `!hunt`, `!pick search`, `!buywpn sword 1`",
        "",
    ]
    current = None
    for spec in _specs():
        if group and spec.group != group and spec.name != group:
            continue
        if spec.group != current:
            current = spec.group
            lines.append(f"▸ {current}")
        alias = f" ({', '.join(spec.aliases)})" if spec.aliases else ""
        lines.append(f"  {spec.usage}{alias}")
        lines.append(f"    {spec.summary}")
    if group and len(lines) <= 3:
        return f"Không có nhóm `{group}`. Gõ `trogiup` để xem tất cả."
    return "\n".join(lines)


def dispatch(player_id: str, channel_id: str, line: str) -> Reply:
    """Run one command. `line` may include a leading `!` or `m!`."""
    raw = (line or "").strip()
    if raw.startswith("m!"):
        raw = raw[2:].strip()
    elif raw.startswith("!"):
        raw = raw[1:].strip()
    if not raw:
        from .panels import help_reply
        return help_reply()
    try:
        parts = shlex.split(raw)
    except ValueError:
        parts = raw.split()
    name = parts[0].lower()
    args = parts[1:]
    spec = _index().get(name)
    if spec is None:
        return coerce(f"Không có lệnh `{name}`. Gõ `help`.")
    ctx = Ctx(player_id=str(player_id), channel_id=str(channel_id), args=args, command=spec.name)
    try:
        return coerce(spec.handler(ctx) or "(không có phản hồi)")
    except UsageError as exc:
        return coerce(f"{exc}\nDùng: `{spec.usage}`")
    except Exception as exc:
        return coerce(f"Lỗi lệnh `{spec.name}`: {exc}")
