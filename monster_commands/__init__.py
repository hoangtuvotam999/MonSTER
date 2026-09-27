"""
Platform-neutral command library for MonSTER.

No Discord, Telegram, or HTTP code lives here. A bot (or a test) calls
`dispatch(player_id, channel_id, line)` and gets chat text back.
"""
from .router import dispatch, help_text, list_commands

__all__ = ["dispatch", "help_text", "list_commands"]
