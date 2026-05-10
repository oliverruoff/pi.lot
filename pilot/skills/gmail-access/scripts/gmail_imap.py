#!/usr/bin/env python3
import argparse, imaplib, json, os, re, sys
from datetime import datetime
from email import policy
from email.parser import BytesParser
from email.header import decode_header, make_header

ROOT = os.path.dirname(os.path.dirname(__file__))

def load_env():
    for p in (os.path.join(ROOT, ".env"), ".env"):
        if os.path.exists(p):
            for line in open(p, encoding="utf-8"):
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line: continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

def out(x): print(json.dumps(x, ensure_ascii=False, indent=2))
def die(msg, code=1): out({"ok": False, "error": msg}); sys.exit(code)
def dec(v):
    if not v: return ""
    try: return str(make_header(decode_header(v)))
    except Exception: return v

def connect(folder):
    load_env()
    user, pwd = os.getenv("GMAIL_EMAIL"), os.getenv("GMAIL_APP_PASSWORD")
    if not user or not pwd: die("Set GMAIL_EMAIL and GMAIL_APP_PASSWORD in environment or .env")
    host, port = os.getenv("GMAIL_IMAP_HOST", "imap.gmail.com"), int(os.getenv("GMAIL_IMAP_PORT", "993"))
    m = imaplib.IMAP4_SSL(host, port)
    m.login(user, pwd)
    typ, _ = m.select(folder)
    if typ != "OK": die(f"Cannot select folder: {folder}")
    return m

def imap_date(s): return datetime.strptime(s, "%Y-%m-%d").strftime("%d-%b-%Y")
def qstr(s): return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'

def criteria(a):
    c = ["UNSEEN" if a.unread else "ALL"]
    for key in ("from", "to", "subject"):
        v = getattr(a, key)
        if v: c += [key.upper(), qstr(v)]
    if a.text: c += ["TEXT", qstr(a.text)]
    if a.since: c += ["SINCE", imap_date(a.since)]
    if a.before: c += ["BEFORE", imap_date(a.before)]
    return " ".join(c)

def fetch_msg(m, uid):
    typ, data = m.uid("fetch", str(uid), "(RFC822)")
    if typ != "OK" or not data or not data[0]: die(f"Message not found: {uid}")
    return BytesParser(policy=policy.default).parsebytes(data[0][1])

def body_and_attachments(msg):
    text = html = ""; atts = []
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.is_multipart(): continue
        disp = (part.get_content_disposition() or "").lower()
        name = part.get_filename()
        ctype = part.get_content_type()
        if disp == "attachment" or name:
            data = part.get_payload(decode=True) or b""
            atts.append({"filename": dec(name) or "attachment", "content_type": ctype, "size": len(data)})
        elif ctype == "text/plain" and not text:
            text = part.get_content()
        elif ctype == "text/html" and not html:
            html = part.get_content()
    return text, html, atts

def meta(uid, msg, include_body=False):
    text, html, atts = body_and_attachments(msg)
    r = {"uid": str(uid), "subject": dec(msg.get("subject")), "from": dec(msg.get("from")), "to": dec(msg.get("to")), "date": dec(msg.get("date")), "message_id": dec(msg.get("message-id")), "attachments": atts}
    if include_body: r.update({"text_body": text, "html_body": html})
    return r

def search(a):
    m = connect(a.folder)
    try:
        typ, data = m.uid("search", None, criteria(a))
        if typ != "OK": die("Search failed")
        uids = data[0].split()[::-1][:a.limit]
        out({"ok": True, "count": len(uids), "messages": [meta(u.decode(), fetch_msg(m, u.decode())) for u in uids]})
    finally: m.logout()

def read(a):
    m = connect(a.folder)
    try: out({"ok": True, "message": meta(a.uid, fetch_msg(m, a.uid), True)})
    finally: m.logout()

def safe(n): return re.sub(r"[^A-Za-z0-9._ -]", "_", n or "attachment")[:160]

def download(a):
    m = connect(a.folder); os.makedirs(a.output_dir, exist_ok=True); files = []
    try:
        msg = fetch_msg(m, a.uid)
        i = 0
        for part in msg.walk():
            name = part.get_filename()
            if not name and part.get_content_disposition() != "attachment": continue
            i += 1; name = safe(dec(name) or f"attachment-{i}")
            path = os.path.join(a.output_dir, name)
            base, ext = os.path.splitext(path); n = 1
            while os.path.exists(path): n += 1; path = f"{base}-{n}{ext}"
            open(path, "wb").write(part.get_payload(decode=True) or b"")
            files.append(path)
        out({"ok": True, "uid": str(a.uid), "files": files})
    finally: m.logout()

def main():
    p = argparse.ArgumentParser(description="Search/read Gmail via IMAP app password. Outputs JSON.")
    p.add_argument("--folder", default="INBOX")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search"); s.add_argument("--folder", default=argparse.SUPPRESS); s.add_argument("--from"); s.add_argument("--to"); s.add_argument("--subject"); s.add_argument("--text"); s.add_argument("--since"); s.add_argument("--before"); s.add_argument("--unread", action="store_true"); s.add_argument("--limit", type=int, default=10); s.set_defaults(fn=search)
    r = sub.add_parser("read"); r.add_argument("--folder", default=argparse.SUPPRESS); r.add_argument("uid"); r.set_defaults(fn=read)
    d = sub.add_parser("download-attachments"); d.add_argument("--folder", default=argparse.SUPPRESS); d.add_argument("uid"); d.add_argument("--output-dir", default="attachments"); d.set_defaults(fn=download)
    a = p.parse_args(); a.fn(a)
if __name__ == "__main__": main()
