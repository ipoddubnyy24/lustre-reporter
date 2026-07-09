"""Build a Teams 'ping' for a backport candidate.

We don't auto-send from the server (no service credentials, and the message
should read as if a person wrote it). Instead we produce a Microsoft Teams
compose deep link: clicking it opens Teams with a 1:1 chat to the reviewer and
the message pre-filled, so the user reviews it and hits Send. A mailto link is
provided as a fallback.
"""

from __future__ import annotations

from urllib.parse import quote

_TEAMS_DEEPLINK = "https://teams.microsoft.com/l/chat/0/0?users={users}&message={message}"


def backport_message(reviewer_name: str, gerrit_branch: str, subject: str,
                     patch_url: str, ticket_lines: list[str]) -> str:
    """A short, human-sounding backport request.

    Deliberately plain — no boilerplate, no 'as requested', no AI tells.
    Greets with the full display name to avoid mis-guessing name order.
    """
    greeting = (reviewer_name or "there").strip()
    lines = [
        f"Hi {greeting}, please consider this patch for "
        f"backport to {gerrit_branch}:",
        f"{subject}",
        f"{patch_url}",
    ]
    if ticket_lines:
        lines.append("")
        lines.append("Ticket: " + "  ".join(ticket_lines))
    lines.append("")
    lines.append("Thanks!")
    return "\n".join(lines)


def compose(reviewer_email: str, reviewer_name: str, gerrit_branch: str,
            subject: str, patch_url: str, ticket_lines: list[str]) -> dict:
    message = backport_message(reviewer_name, gerrit_branch, subject,
                               patch_url, ticket_lines)
    teams_url = _TEAMS_DEEPLINK.format(
        users=quote(reviewer_email, safe=""),
        message=quote(message, safe=""),
    )
    subj = f"Backport request: {subject}"
    mailto_url = (
        f"mailto:{reviewer_email}"
        f"?subject={quote(subj, safe='')}"
        f"&body={quote(message, safe='')}"
    )
    return {
        "reviewer": reviewer_name,
        "email": reviewer_email,
        "message": message,
        "teams_url": teams_url,
        "mailto_url": mailto_url,
    }
