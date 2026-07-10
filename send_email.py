#!/usr/bin/env python3
"""Send a Gmail SMTP notification.

Body is read from stdin. Subject can be passed as argv[1].
Recipients come from EMAIL_TO / EMAIL_CC env vars; the app password from
GMAIL_APP_PASSWORD, falling back to the macOS Keychain for local runs.
"""
import os
import smtplib
import subprocess
import sys
from email.message import EmailMessage

ADDRESS = os.environ.get("EMAIL_TO", "")
CC = os.environ.get("EMAIL_CC", "")
KEYCHAIN_SERVICE = "fizz-monitor-gmail"


def get_password() -> str:
    pwd = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
    if pwd:
        return pwd
    if sys.platform == "darwin":
        return subprocess.run(
            ["security", "find-generic-password",
             "-a", ADDRESS, "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    raise RuntimeError("GMAIL_APP_PASSWORD is not set")


def main() -> None:
    if not ADDRESS:
        raise RuntimeError("EMAIL_TO is not set")
    subject = sys.argv[1] if len(sys.argv) > 1 else "Fizz Leiden update"
    body = sys.stdin.read().strip() or "(empty body)"

    msg = EmailMessage()
    msg["From"] = ADDRESS
    msg["To"] = ADDRESS
    if CC:
        msg["Cc"] = CC
    msg["Subject"] = subject
    msg.set_content(body)

    pwd = get_password()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as s:
        s.login(ADDRESS, pwd)
        s.send_message(msg)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"send_email failed: {e}", file=sys.stderr)
        sys.exit(1)
