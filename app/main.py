"""Yahoo Mail Bridge - tiny HTTP API over Yahoo IMAP/SMTP.

Auth: every /v1/* call needs  Authorization: Bearer <API_TOKEN>.
The Yahoo app password lives only in this host's environment, never in
requests, responses, or logs.
"""

import os

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from .yahoo import list_folders, read_message, search_messages, send_message

API_TOKEN = os.environ.get("API_TOKEN", "")
security = HTTPBearer(auto_error=False)

app = FastAPI(title="Yahoo Mail Bridge", version="1.0.0")


def require_token(
    creds: HTTPAuthorizationCredentials = Depends(security),
) -> bool:
    if not API_TOKEN or not creds or creds.credentials != API_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")
    return True


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/v1/folders")
def folders(_: bool = Depends(require_token)):
    try:
        return {"ok": True, "folders": list_folders()}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/v1/search")
def search(
    mailbox: str = "INBOX",
    q: str = Query(default=""),
    limit: int = Query(default=50, le=200),
    _: bool = Depends(require_token),
):
    try:
        return {
            "ok": True,
            "messages": search_messages(mailbox, q, limit),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/v1/read")
def read(
    mailbox: str = "INBOX",
    uid: int = Query(...),
    _: bool = Depends(require_token),
):
    try:
        msg = read_message(mailbox, uid)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    if msg is None:
        raise HTTPException(status_code=404, detail="message not found")
    return {"ok": True, "message": msg}


class SendBody(BaseModel):
    to: str
    subject: str
    body: str


@app.post("/v1/send")
def send(payload: SendBody, _: bool = Depends(require_token)):
    try:
        send_message(payload.to, payload.subject, payload.body)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"ok": True}
