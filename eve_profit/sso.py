"""EVE SSO v2 login: OAuth2 authorization-code + PKCE (public client, no secret).
Register an app at https://developers.eveonline.com with callback http://localhost:8765/callback
and the scopes in SCOPES, then set EVE_CLIENT_ID (or pass --client-id)."""
import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.parse
import urllib.request
import webbrowser

from .config import USER_AGENT

AUTH_URL = "https://login.eveonline.com/v2/oauth/authorize"
TOKEN_URL = "https://login.eveonline.com/v2/oauth/token"
CALLBACK_PORT = 8765
CALLBACK = f"http://localhost:{CALLBACK_PORT}/callback"
SCOPES = [
    "esi-location.read_location.v1",
    "esi-location.read_ship_type.v1",
    "esi-skills.read_skills.v1",
    "esi-wallet.read_character_wallet.v1",
    "esi-assets.read_assets.v1",
    "esi-characters.read_blueprints.v1",
    "esi-industry.read_character_jobs.v1",
    "esi-markets.structure_markets.v1",
    "esi-universe.read_structures.v1",
    "esi-characters.read_loyalty.v1",
    "esi-characters.read_standings.v1",
    "esi-ui.write_waypoint.v1",      # Stage 6 route automation (sets waypoints only)
]
TOKEN_FILE = "tokens.json"


def make_pkce():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def auth_url(client_id, state, challenge):
    q = urllib.parse.urlencode({
        "response_type": "code", "redirect_uri": CALLBACK, "client_id": client_id,
        "scope": " ".join(SCOPES), "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})
    return f"{AUTH_URL}?{q}"


def character_from_jwt(access_token):
    """Claims are read without signature check: the token came straight from CCP's
    token endpoint over TLS. 'sub' looks like CHARACTER:EVE:<id>."""
    payload = access_token.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    return int(claims["sub"].split(":")[-1]), claims.get("name", "")


def _post(data, post=None):
    if post:
        return post(data)
    req = urllib.request.Request(
        TOKEN_URL, data=urllib.parse.urlencode(data).encode(),
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _store(tok, path):
    cid, name = character_from_jwt(tok["access_token"])
    rec = {"character_id": cid, "character_name": name,
           "access_token": tok["access_token"], "refresh_token": tok["refresh_token"],
           "expires_at": time.time() + tok["expires_in"] - 30}
    with open(path, "w") as f:
        json.dump(rec, f, indent=2)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return rec


def login(client_id, path=TOKEN_FILE, open_browser=True, post=None):
    """Blocks until the browser redirects back to the local callback."""
    verifier, challenge = make_pkce()
    state = secrets.token_urlsafe(16)
    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got["code"], got["state"] = q.get("code", [""])[0], q.get("state", [""])[0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Login complete. You can close this tab.")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", CALLBACK_PORT), H)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    url = auth_url(client_id, state, challenge)
    print("Open this URL if the browser does not start:\n" + url)
    if open_browser:
        webbrowser.open(url)
    deadline = time.time() + 300
    while "code" not in got and time.time() < deadline:
        time.sleep(0.2)
    srv.server_close()
    if got.get("state") != state or not got.get("code"):
        raise RuntimeError("SSO login failed or state mismatch")
    tok = _post({"grant_type": "authorization_code", "code": got["code"],
                 "client_id": client_id, "code_verifier": verifier}, post)
    return _store(tok, path)


def get_token(client_id, path=TOKEN_FILE, post=None):
    """Valid access token, refreshing if needed. -> (token, character_id)."""
    with open(path) as f:
        rec = json.load(f)
    if time.time() >= rec["expires_at"]:
        tok = _post({"grant_type": "refresh_token", "refresh_token": rec["refresh_token"],
                     "client_id": client_id}, post)
        rec = _store(tok, path)
    return rec["access_token"], rec["character_id"]
