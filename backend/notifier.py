"""
Called from exactly one place: the end of diff_engine.compute_changes()'s
loop - once per `changes` row written, never once per poll. A no-op poll
(nothing changed) must fire zero notifications.

No OS desktop popups here on purpose - the app is pull-only: open the
dashboard and see what changed in the Margin Notes panel, nothing pushes
itself at you. This function is a no-op hook until you wire in an actual
push channel (email / WhatsApp) for things you specifically want pushed,
e.g. only overdue followups, not every balance tick.
"""
from __future__ import annotations

import sqlite3

from config import settings


def notify(change: sqlite3.Row) -> None:
    if not settings.alerts.enabled:
        return
    # TODO: email hook - e.g. smtplib, keyed off change["change_type"] if you
    #       only want certain kinds pushed (new_bill, overdue followups, etc.)
    # TODO: WhatsApp hook - e.g. Twilio/WhatsApp Business API, same pattern
    pass
