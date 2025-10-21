# DO robienia od nowa, tu nie bedzie filtrow, tylko pobranie calego zakresu 
# dla TG bedzie pobierac po userach i projektach (oraz taskach?)
# dla TT bedzie pobierac po userach i holidays 
# mozliwe okreslenie okresu pobierania na miesiac, ale docelowo bez okreslienia zeby miec mozliwosc budowania rocznych statystyk



import base64
import os
from typing import List, Dict, Any, Optional
import requests

TOGGL_BASE = os.getenv("TOGGL_BASE_URL", "https://api.track.toggl.com/api/v9")
TOGGL_TOKEN = os.getenv("TOGGL_API_TOKEN", "").strip()

def _auth_header() -> Dict[str, str]:
    """Toggl Track uses Basic Auth: <api_token>:api_token (base64)."""
    token_bytes = f"{TOGGL_TOKEN}:api_token".encode("utf-8")
    return {
        "Authorization": "Basic " + base64.b64encode(token_bytes).decode("ascii"),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

def get_me() -> Dict[str, Any]:
    """Small sanity check: who am I? Useful to confirm token validity."""
    url = f"{TOGGL_BASE}/me"
    r = requests.get(url, headers=_auth_header(), timeout=60)
    r.raise_for_status()
    return r.json()

def get_time_entries(start_iso: str, end_iso: str, workspace_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Fetch time entries for the current user between start_iso and end_iso (ISO8601, UTC, e.g. 2025-10-01T00:00:00Z).
    If workspace_id is provided, Toggl will filter by that workspace (depends on permissions).
    """
    url = f"{TOGGL_BASE}/me/time_entries"
    params = {"start_date": start_iso, "end_date": end_iso}
    if workspace_id:
        params["workspace_id"] = workspace_id
    r = requests.get(url, headers=_auth_header(), params=params, timeout=120)
    r.raise_for_status()
    return r.json()
