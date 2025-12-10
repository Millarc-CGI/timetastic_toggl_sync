from fastapi import FastAPI, Request, HTTPException
import hmac, hashlib, time
import subprocess
import threading
from pathlib import Path
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

@app.post("/project")
async def project_handler(req: Request):
    """
    Slack slash command handler for /project.
    Expects the project name in the command text.
    """
    body = await req.body()
    headers = req.headers
    verify_slack_request(headers["x-slack-signature"], headers["x-slack-request-timestamp"], body.decode())
    form = await req.form()

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
