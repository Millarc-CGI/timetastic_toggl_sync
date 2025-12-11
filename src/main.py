from fastapi import FastAPI, Request, HTTPException
import hmac, hashlib, time
import subprocess
import threading
from pathlib import Path
from .config import load_settings
from .services.slack_service import SlackService

settings = load_settings()
app = FastAPI()
slack_service = SlackService(settings)


def _normalize_email(email: str) -> str:
    """Normalize email using alias map from settings."""
    email_l = (email or "").strip().lower()
    if not email_l:
        return ""
    return settings.email_aliases.get(email_l, email_l)


def verify_slack_request(slack_signature, slack_timestamp, body):
    if abs(time.time() - int(slack_timestamp)) > 60 * 5:
        raise HTTPException(status_code=400, detail="Timestamp too old")
    basestring = f"v0:{slack_timestamp}:{body}".encode("utf-8")
    my_signature = "v0=" + hmac.new(settings.slack_signing_secret.encode(), basestring, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(my_signature, slack_signature):
        raise HTTPException(status_code=400, detail="Bad signature")

@app.post("/slack")
async def project_handler(req: Request):
    """
    Slack slash command handler for /project.
    Expects the project name in the command text.
    """
    body = await req.body()
    headers = req.headers
    verify_slack_request(headers["x-slack-signature"], headers["x-slack-request-timestamp"], body.decode())
    form = await req.form()

    user_id = form.get("user_id")
    if not user_id:
        return {"response_type": "ephemeral", "text": "❌ Nie udało się zweryfikować użytkownika Slack."}

    slack_user = slack_service.get_user_info(user_id)
    user_email = _normalize_email(slack_user.get("profile", {}).get("email", "") if slack_user else "")
    if not user_email:
        return {"response_type": "ephemeral", "text": "❌ Nie mogę ustalić Twojego e-maila w Slacku. Skontaktuj się z administratorem."}

    if not (settings.is_producer(user_email) or settings.is_admin(user_email)):
        return {"response_type": "ephemeral", "text": "⛔ Nie masz uprawnień do uruchamiania komendy"}

    project_name = (form.get("text") or "").strip()

    if not project_name:
        return {"response_type": "ephemeral", "text": "❌ Podaj nazwę projektu po komendzie, np. `/project Project ABC`"}

    # Fire-and-forget: uruchom report-project-stats --project-name <name> --target production --send
    def _run_report(project_name: str):
        try:
            repo_root = Path(__file__).resolve().parent.parent
            cmd = [
                "python",
                "-m",
                "src.cli",
                "report-project-stats",
                "--project-name",
                project_name,
                "--target",
                "production",
                "--send",
            ]
            subprocess.run(cmd, cwd=repo_root, check=False)
        except Exception as exc:
            print(f"[project_handler] report-monthly failed: {exc}")

    threading.Thread(target=_run_report, args=(project_name,), daemon=True).start()

    return {
        "response_type": "ephemeral",
        "text": f"✅ Uruchomiono report-project-stats --project-name \"{project_name}\" --target production --send"
    }
