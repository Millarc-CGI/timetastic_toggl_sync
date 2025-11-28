from fastapi import FastAPI, Request, HTTPException
import hmac, hashlib, time
from .config import load_settings
settings = load_settings()
app = FastAPI()


def verify_slack_request(slack_signature, slack_timestamp, body):
    if abs(time.time() - int(slack_timestamp)) > 60 * 5:
        raise HTTPException(status_code=400, detail="Timestamp too old")
    basestring = f"v0:{slack_timestamp}:{body}".encode("utf-8")
    my_signature = "v0=" + hmac.new(settings.slack_signing_secret.encode(), basestring, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(my_signature, slack_signature):
        raise HTTPException(status_code=400, detail="Bad signature")

@app.post("/slack")
async def slack_handler(req: Request):
    body = await req.body()
    headers = req.headers
    verify_slack_request(headers["x-slack-signature"], headers["x-slack-request-timestamp"], body.decode())
    form = await req.form()
    command = form.get("command")
    text = form.get("text")
    return {"response_type": "ephemeral", "text": f"Otrzymałem {command} z tekstem: {text}"}
