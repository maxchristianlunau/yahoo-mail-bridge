"""IMAP/SMTP access to a Yahoo mailbox.

Credentials come only from environment variables set by the person hosting
this service (YAHOO_EMAIL / YAHOO_APP_PASSWORD). They are never logged,
never returned by any endpoint, and never written to disk by this code.
"""

import email
import imaplib
import os
import smtplib
from email.header import decode_header
from email.message import EmailMessage

IMAP_HOST, IMAP_PORT = "imap.mail.yahoo.com", 993
SMTP_HOST, SMTP_PORT = "smtp.mail.yahoo.com", 465


def _creds():
    addr = os.environ.get("YAHOO_EMAIL", "").strip()
    pwd = os.environ.get("YAHOO_APP_PASSWORD", "").strip()
    if not addr or not pwd:
        raise RuntimeError("YAHOO_EMAIL / YAHOO_APP_PASSWORD are not configured")
    return addr, pwd


def _imap():
    addr, pwd = _creds()
    conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=30)
    conn.login(addr, pwd)
    return conn


def _decode(value):
    if not value:
        return ""
    out = ""
    for text, charset in decode_header(value):
        if isinstance(text, bytes):
            out += text.decode(charset or "utf-8", errors="replace")
        else:
            out += text
    return out


def _strip_html(html):
    import re

    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]*>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _body_text(msg):
    plain, html = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            if "attachment" in (part.get("Content-Disposition") or ""):
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            text = payload.decode(
                part.get_content_charset() or "utf-8", errors="replace"
            )
            if part.get_content_type() == "text/plain" and not plain:
                plain = text
            elif part.get_content_type() == "text/html" and not html:
                html = text
    else:
        payload = msg.get_payload(decode=True)
        if payload is None:
            return str(msg.get_payload())
        text = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
        if msg.get_content_type() == "text/html":
            html = text
        else:
            plain = text
    if plain.strip():
        return plain
    return _strip_html(html)


def list_folders():
    conn = _imap()
    try:
        _, data = conn.list()
        folders = []
        for line in data:
            s = line.decode("utf-8", errors="replace")
            # '(\\HasNoChildren) "/" "INBOX"' -> INBOX
            name = s.rsplit('"', 2)[-2] if s.count('"') >= 2 else s.split()[-1]
            folders.append(name)
        return folders
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def _criterion(query):
    q = (query or "").strip()
    low = q.lower()
    if low.startswith("from:"):
        return ["FROM", q[5:].strip()]
    if low.startswith("subject:"):
        return ["SUBJECT", q[8:].strip()]
    if low.startswith("to:"):
        return ["TO", q[3:].strip()]
    return ["TEXT", q] if q else ["ALL"]


def search_messages(mailbox="INBOX", query="", limit=50):
    conn = _imap()
    try:
        typ, _ = conn.select(mailbox, readonly=True)
        if typ != "OK":
            raise RuntimeError(f"cannot open mailbox {mailbox}")
        _, data = conn.uid("search", None, *_criterion(query))
        uids = data[0].split()
        uids = uids[::-1][: max(1, min(limit, 200))]
        results = []
        for uid in uids:
            _, msg_data = conn.uid(
                "fetch", uid, "(BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE)])"
            )
            if not msg_data or not msg_data[0]:
                continue
            m = email.message_from_bytes(msg_data[0][1])
            results.append(
                {
                    "uid": int(uid),
                    "from": _decode(m.get("From")),
                    "to": _decode(m.get("To")),
                    "subject": _decode(m.get("Subject")),
                    "date": m.get("Date", ""),
                }
            )
        return results
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def read_message(mailbox="INBOX", uid=0):
    conn = _imap()
    try:
        typ, _ = conn.select(mailbox, readonly=True)
        if typ != "OK":
            raise RuntimeError(f"cannot open mailbox {mailbox}")
        _, msg_data = conn.uid("fetch", str(uid), "(BODY.PEEK[])")
        if not msg_data or not msg_data[0]:
            return None
        m = email.message_from_bytes(msg_data[0][1])
        return {
            "uid": int(uid),
            "from": _decode(m.get("From")),
            "to": _decode(m.get("To")),
            "subject": _decode(m.get("Subject")),
            "date": m.get("Date", ""),
            "body": _body_text(m)[:20000],
        }
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def send_message(to_addr, subject, body):
    addr, pwd = _creds()
    msg = EmailMessage()
    msg["From"] = addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
        smtp.login(addr, pwd)
        smtp.send_message(msg)
