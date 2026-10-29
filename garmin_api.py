"""Read-only access to the Garmin Personal API, using only Python's standard library.

The API key is read from .env.local and exchanged for a 24-hour access token,
which is cached in data/token.json and renewed once it is 20 hours old.
"""
import json
import os
import ssl
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
ENV_FILE = os.path.join(ROOT, ".env.local")
TOKEN_FILE = os.path.join(DATA, "token.json")
BASE = "https://personal.connectapi.garmin.com"
TOKEN_URL = BASE + "/personalapitoken-service/personal-api/personal-api-key/token"
TOKEN_MAX_AGE = 20 * 3600

# Python from python.org on macOS ships without trusted certificates; fall back
# to the system's own list so HTTPS works without installing anything.
_SSL = ssl.create_default_context()
if not _SSL.get_ca_certs() and os.path.exists("/etc/ssl/cert.pem"):
    _SSL = ssl.create_default_context(cafile="/etc/ssl/cert.pem")


class GarminError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def _read_key():
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE) as f:
            for line in f:
                if line.startswith("GARMIN_PERSONAL_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if key:
                        return key
    raise GarminError("Your API key is missing. Open .env.local and paste it after the = sign.")


def _new_token():
    req = urllib.request.Request(
        TOKEN_URL, data=b"", method="POST",
        headers={"Authorization": "ApiKey " + _read_key(), "Accept": "text/plain"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30, context=_SSL) as r:
            token = r.read().decode().strip().strip('"')
    except urllib.error.HTTPError as e:
        raise GarminError(
            f"Garmin refused the API key (HTTP {e.code}). It may be mistyped or expired: "
            "check .env.local, or make a new key in Garmin Connect.", e.code) from None
    if not token:
        raise GarminError("Garmin returned an empty token. Check the key in .env.local.")
    os.makedirs(DATA, exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        json.dump({"token": token, "created": time.time()}, f)
    os.chmod(TOKEN_FILE, 0o600)
    return token


def get_token(force=False):
    if not force and os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE) as f:
                saved = json.load(f)
            if time.time() - saved["created"] < TOKEN_MAX_AGE:
                return saved["token"]
        except (ValueError, KeyError):
            pass
    return _new_token()


def get(path, retries=4):
    """GET a path and return parsed JSON (None for an empty body).

    Retries on 429/502/503 and renews the token once on 401. A 500 is raised
    straight away so the caller can shrink its date range.
    """
    renewed = False
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            BASE + path,
            headers={"Authorization": "Bearer " + get_token(), "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60, context=_SSL) as r:
                body = r.read()
            time.sleep(0.4)
            return json.loads(body) if body.strip() else None
        except urllib.error.HTTPError as e:
            if e.code == 401 and not renewed:
                get_token(force=True)
                renewed = True
                continue
            if e.code in (429, 502, 503) and attempt < retries:
                time.sleep(3 * (attempt + 1))
                continue
            raise GarminError(f"HTTP {e.code} for {path.split('?')[0]}", e.code) from None
        except urllib.error.URLError as e:
            if attempt < retries:
                time.sleep(3)
                continue
            raise GarminError(f"Network problem: {e.reason}") from None
