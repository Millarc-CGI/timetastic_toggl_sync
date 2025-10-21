# DO robienia od nowa, tu nie bedzie filtrow, tylko pobranie calego zakresu 
# dla TG bedzie pobierac po userach i projektach (oraz taskach?)
# dla TT bedzie pobierac po userach i holidays 
# mozliwe okreslenie okresu pobierania na miesiac, ale docelowo bez okreslienia zeby miec mozliwosc budowania rocznych statystyk



# src/clients/timetastic.py
import os
from typing import List, Dict, Any, Optional
import requests

TT_BASE = os.getenv("TIMETASTIC_BASE_URL", "https://app.timetastic.co.uk/api")
TT_TOKEN = os.getenv("TIMETASTIC_API_TOKEN", "").strip()


def _auth_header() -> Dict[str, str]:
    return {"Authorization": f"Bearer {TT_TOKEN}", "Accept": "application/json"}


def _get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    if not TT_TOKEN:
        raise RuntimeError("TIMETASTIC_API_TOKEN is not set")
    url = f"{TT_BASE.rstrip('/')}/{path.lstrip('/')}"
    r = requests.get(url, headers=_auth_header(), params=params or {}, timeout=90)
    r.raise_for_status()
    return r.json()


def get_holidays(
    start_iso: str,                 # "YYYY-MM-DDTHH:MM:SSZ"
    end_iso: str,                   # "YYYY-MM-DDTHH:MM:SSZ"
    users_ids: Optional[List[int]] = None,   # e.g. [12,34]
    status: Optional[str] = "Approved",      # "Approved" by default; change if needed
    include_user: bool = False,               # if True, attach user details to each holiday under key "user"
) -> List[Dict[str, Any]]:
    """
    Fetch Timetastic holidays with common filters.
    Returns a flat list of holiday objects.

    If include_user=True, each holiday dict gets an extra key `user` with
    { firstName, lastName, email, department, currentYearAllowance, allowanceRemaining }.
    """
    params: Dict[str, Any] = {
        "Start": start_iso,
        "End": end_iso,
    }
    if users_ids:
        params["UsersIds"] = ",".join(str(x) for x in users_ids)
    if status:
        params["Status"] = status

    results: List[Dict[str, Any]] = []
    page = 1

    # simple in-memory cache to avoid repeated /users/{id} calls
    _USER_CACHE: Dict[int, Dict[str, Any]] = {}

    def _holiday_user_id(item: Dict[str, Any]) -> Optional[int]:
        # try common shapes: UserId, userId, user.id, User.Id
        if not isinstance(item, dict):
            return None
        # case-insensitive keys
        lower = {k.lower(): v for k, v in item.items()}
        for k in ("userid", "user_id"):
            if k in lower and isinstance(lower[k], (int, str)):
                try:
                    return int(lower[k])
                except (TypeError, ValueError):
                    pass
        # nested `user` object
        u = lower.get("user")
        if isinstance(u, dict):
            nested = {k.lower(): v for k, v in u.items()}
            val = nested.get("id")
            try:
                return int(val) if val is not None else None
            except (TypeError, ValueError):
                return None
        return None

    while True:
        params["PageNumber"] = page
        data = _get("/holidays", params=params)
        items = data if isinstance(data, list) else data.get("holidays") or data.get("items") or []
        items = [i for i in items if isinstance(i, dict)]
        if not items:
            break

        if include_user:
            for it in items:
                uid = _holiday_user_id(it)
                if uid is not None:
                    if uid not in _USER_CACHE:
                        try:
                            _USER_CACHE[uid] = get_user(uid)
                        except Exception:
                            _USER_CACHE[uid] = {}
                    it["user"] = _USER_CACHE.get(uid) or {}
                else:
                    it["user"] = {}

        results.extend(items)
        # API najczęściej zwraca <=100 na stronę – jeśli mniej, to koniec
        if len(items) < 100:
            break
        page += 1

    return results


def _extract_case_insensitive(src: Dict[str, Any], *keys: str) -> Any:
    """Get the first present key from src in a case-insensitive way (supports dot paths)."""
    if not isinstance(src, dict):
        return None
    lower_map = {k.lower(): v for k, v in src.items()}
    for key in keys:
        parts = key.split(".")
        cur = lower_map
        val: Any = None
        ok = True
        for p in parts:
            if not isinstance(cur, dict):
                ok = False
                break
            # build case-insensitive layer for nested dicts
            cur = {k.lower(): v for k, v in cur.items()}
            if p.lower() not in cur:
                ok = False
                break
            val = cur[p.lower()]
            cur = val
        if ok:
            return val
    return None


def get_user(user_id: int) -> Dict[str, Any]:
    """
    Fetch a single Timetastic user and return a normalized subset of fields:
    {
      "firstName": str | None,
      "lastName": str | None,
      "email": str | None,
      "department": str | None,
      "currentYearAllowance": int | float | None,
      "allowanceRemaining": int | float | None,
      "raw": dict  # original payload for debugging
    }
    """
    data = _get(f"/users/{user_id}")

    # Some Timetastic responses may embed department as object or string.
    department_name = None
    dep_obj = _extract_case_insensitive(data, "department")
    if isinstance(dep_obj, dict):
        department_name = _extract_case_insensitive(dep_obj, "name", "Name")
    elif isinstance(dep_obj, str):
        department_name = dep_obj

    out = {
        "firstName": _extract_case_insensitive(data, "firstName", "FirstName", "first_name"),
        "lastName": _extract_case_insensitive(data, "lastName", "LastName", "last_name"),
        "email": _extract_case_insensitive(data, "email", "Email"),
        "department": department_name,
        "currentYearAllowance": _extract_case_insensitive(data, "currentYearAllowance", "CurrentYearAllowance"),
        "allowanceRemaining": _extract_case_insensitive(data, "allowanceRemaining", "AllowanceRemaining"),
        "raw": data,
    }
    return out
