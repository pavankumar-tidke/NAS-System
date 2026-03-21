"""
Human-readable MongoDB startup failures (avoid dumping full PyMongo stacks to the console).
"""

from __future__ import annotations

import textwrap

from pymongo.errors import ServerSelectionTimeoutError


def summarize_mongo_error(exc: BaseException) -> str:
    """One-line summary for logging and RuntimeError messages."""
    msg = str(exc).strip()
    if "SSL handshake failed" in msg or "TLSV1_ALERT" in msg or "tlsv1 alert" in msg.lower():
        return "MongoDB TLS/SSL handshake failed (see startup banner for fixes)."
    if "ServerSelectionTimeoutError" in type(exc).__name__ or "No primary found" in msg:
        return "MongoDB server selection timed out — unreachable cluster or network blocked."
    if "Authentication failed" in msg:
        return "MongoDB authentication failed — check username, password, and authSource in MONGO_URI."
    return f"MongoDB error: {msg[:180]}{'…' if len(msg) > 180 else ''}"


def mongo_startup_banner(exc: BaseException) -> str:
    """
    Multi-line message printed to stderr when the DB fails during app startup.
    """
    detail = str(exc).strip()
    snippet = detail if len(detail) <= 500 else detail[:500] + "…"
    wrapped = textwrap.fill(snippet, width=70)

    tips: list[str] = []
    low = detail.lower()
    if "ssl" in low or "tls" in low:
        tips = [
            "TLS / SSL (common with Atlas + Python 3.12+ on macOS)",
            "  • We pass tlsCAFile=certifi.where() for mongodb+srv — run: pip install -U certifi pymongo motor",
            "  • Copy the URI again from Atlas → Connect → Drivers → Python (3.12+)",
            "  • Atlas → Network Access: add your current IP (or 0.0.0.0/0 for dev only)",
            "  • Try another network/VPN if a corporate firewall intercepts TLS",
        ]
    elif isinstance(exc, ServerSelectionTimeoutError) or "timeout" in low:
        tips = [
            "Network / server unreachable",
            "  • Confirm the cluster is running and MONGO_URI is correct",
            "  • Check Atlas IP allowlist and local firewall/VPN",
        ]
    else:
        tips = [
            "General",
            "  • Verify MONGO_URI, MONGO_DB_NAME (if URI has no /dbname), and database user permissions",
        ]

    bar = "=" * 72
    lines = [
        "",
        bar,
        "  MongoDB startup failed — fix the issue below, then restart the server.",
        bar,
        "",
        "  What went wrong:",
        "",
    ]
    lines.extend("  " + ln for ln in wrapped.splitlines())
    lines.extend(
        [
            "",
            bar,
            "  What to try:",
            "",
        ]
    )
    for t in tips:
        lines.append("  " + t)
    lines.extend(["", bar, ""])
    return "\n".join(lines)
