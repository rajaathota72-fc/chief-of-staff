"""
Email tools, bound to a specific Inbox connector via `build_email_tools`.

Using a factory (instead of module-level globals) keeps this multi-tenant safe:
each founder's CLI/agent run gets its own Inbox instance, and the closures below
capture that instance rather than reaching for shared state.
"""

from __future__ import annotations

from strands import tool

from connectors.base import Inbox


def build_email_tools(inbox: Inbox) -> list:

    @tool
    def list_unread_emails() -> list[dict]:
        """List all unread emails in the founder's inbox, with sender, subject, and body."""
        return [
            {
                "id": e.id,
                "sender": e.sender,
                "sender_name": e.sender_name,
                "subject": e.subject,
                "body": e.body,
                "received_at": e.received_at,
            }
            for e in inbox.list_unread()
        ]

    @tool
    def send_email_reply(email_id: str, reply_body: str) -> str:
        """
        Send a reply to an email and mark it handled. Only call this when you are
        confident this is the right reply to send autonomously (per the founder's
        preferences) - if unsure, use escalate_item instead.

        Args:
            email_id: the id of the email being replied to.
            reply_body: the full text of the reply to send.
        """
        inbox.send_reply(email_id, reply_body)
        return f"Reply sent for {email_id} and marked handled."

    @tool
    def snooze_email(email_id: str, reason: str) -> str:
        """
        Snooze an email that doesn't need action right now (e.g. a newsletter,
        or a social email that can wait). Removes it from the active queue
        without sending a reply.

        Args:
            email_id: the id of the email to snooze.
            reason: brief reason it's being snoozed.
        """
        inbox.mark_status(email_id, "snoozed")
        return f"Email {email_id} snoozed: {reason}"

    return [list_unread_emails, send_email_reply, snooze_email]
