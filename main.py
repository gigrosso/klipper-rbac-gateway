"""
klipper-rbac-gateway — login screen and role-based access control
in front of Mainsail and Moonraker.

  Browser -> nginx (auth_request) -> gateway (127.0.0.1:7200) -> Moonraker (127.0.0.1:7125)

- nginx asks the gateway on every request whether there is a valid session (cookie).
  No session -> login page. This protects Mainsail, the API and the webcam.
- Users, passwords (scrypt) and roles live in the gateway's own SQLite database.
- The gateway talks to Moonraker with Moonraker's API key (stored in a file).
- The first admin created is the "primary admin": its role can never be changed
  and it can never be deleted (neither from the UI nor from the command line).
- The "Users" tab inside Mainsail's Interface Settings comes from ui.js.

Command line:
  python main.py apikey                  fetch and store Moonraker's API key
  python main.py create <user> <role>    create a user (prompts for the password)
  python main.py passwd <user>           change a user's password
  python main.py role <user> <role>      change a user's role
  python main.py remove <user>
  python main.py list
Roles: viewer, operator, admin
"""
import asyncio
import fnmatch
import getpass
import hashlib
import hmac
import html
import json
import logging
import os
import posixpath
import re
import secrets
import sqlite3
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import websockets
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.background import BackgroundTask
from starlette.datastructures import UploadFile

# =========================================================== SETTINGS
# All settings can be overridden with environment variables (see README).
MOONRAKER_URL = os.environ.get("RBAC_MOONRAKER_URL", "http://127.0.0.1:7125").rstrip("/")
MOONRAKER_WS = MOONRAKER_URL.replace("http://", "ws://", 1).replace("https://", "wss://", 1) + "/websocket"
DATA_DIR = Path(os.environ.get("RBAC_DATA_DIR", Path.home() / "printer_data" / "gateway")).expanduser()
DB_PATH = DATA_DIR / "rbac.db"
APIKEY_PATH = DATA_DIR / "api_key"
SESSION_DAYS = int(os.environ.get("RBAC_SESSION_DAYS", "7"))
SECURE_COOKIE = os.environ.get("RBAC_SECURE_COOKIE", "0") == "1"   # set to 1 when served over HTTPS
LOGIN_TITLE = os.environ.get("RBAC_LOGIN_TITLE", "3D Printer")
COOKIE = "rbac_session"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("rbac")

# =========================================================== ROLES
# JSON-RPC methods any logged-in connection may call.
PUBLIC_RPC = ["server.connection.identify", "access.get_user", "access.info", "access.oneshot_token"]

READ_RPC = [
    "printer.info", "printer.objects.*", "printer.query_endstops.status",
    "printer.gcode.help",
    "printer.emergency_stop",  # emergency stop is allowed for everyone (safety decision)
    "server.info", "server.config", "server.temperature_store", "server.gcode_store",
    "server.files.list", "server.files.roots", "server.files.get_directory",
    "server.files.metadata", "server.files.thumbnails",
    "server.history.list", "server.history.totals", "server.history.get_job",
    "server.webcams.list", "server.webcams.get_item",
    "server.database.list", "server.database.get_item",
    "server.announcements.list", "server.job_queue.status",
    "machine.system_info", "machine.proc_stats", "machine.update.status",
]

OPERATOR_RPC = READ_RPC + [
    "printer.print.*",       # start, pause, resume, cancel
    "printer.gcode.script",  # filtered by OPERATOR_GCODE
    "server.files.delete_file", "server.files.move", "server.files.copy",
    "server.files.post_directory", "server.files.delete_directory",
    "server.files.metascan", "server.job_queue.*",
    "server.database.post_item", "server.database.delete_item",
    "server.announcements.dismiss",
]

# Commands an operator may send from the console / buttons.
# Allowing a macro means trusting everything the macro does internally.
OPERATOR_GCODE = [
    "G28", "G90", "G91", "G0", "G1", "M84", "M18", "M400", "M117", "M112",
    "M104", "M109", "M140", "M190", "M106", "M107", "M220", "M221",
    "SET_HEATER_TEMPERATURE", "TURN_OFF_HEATERS", "SET_FAN_SPEED",
    "SET_GCODE_OFFSET", "PAUSE", "RESUME", "CANCEL_PRINT",
    "BED_MESH_CALIBRATE", "BED_MESH_PROFILE", "GET_POSITION", "QUERY_ENDSTOPS",
    "LOAD_FILAMENT", "UNLOAD_FILAMENT", "RESPOND",
]

# Commands rejected INSIDE .gcode files uploaded by non-admins.
BLOCKED_IN_FILES = [
    "SAVE_CONFIG", "FIRMWARE_RESTART", "RESTART", "SET_KINEMATIC_POSITION",
    "FORCE_MOVE", "SET_STEPPER_ENABLE", "PID_CALIBRATE", "SAVE_VARIABLE",
]

# HTTP routes allowed for any logged-in user.
COMMON_HTTP = [
    "GET /access/oneshot_token", "GET /access/info", "GET /access/user",
    "GET /server/files/config/.theme/*",  # Mainsail theme / logo
]

ROLES = {
    "viewer": {
        "rpc": READ_RPC,
        "http": ["GET /server/files/gcodes/*", "GET /server/files/timelapse/*"],
        "gcode": [],
        "writable_roots": [],
    },
    "operator": {
        "rpc": OPERATOR_RPC,
        "http": ["GET /server/files/gcodes/*", "GET /server/files/timelapse/*",
                 "POST /server/files/upload", "DELETE /server/files/gcodes/*"],
        "gcode": OPERATOR_GCODE,
        "writable_roots": ["gcodes"],
    },
    "admin": {"rpc": ["*"], "http": ["*"], "gcode": ["*"], "writable_roots": ["*"]},
}

FILE_WRITE_METHODS = {
    "server.files.delete_file": ["path"], "server.files.delete_directory": ["path"],
    "server.files.post_directory": ["path"], "server.files.move": ["source", "dest"],
    "server.files.copy": ["source", "dest"],
}
WRITABLE_NAMESPACES = {"mainsail"}  # non-admins may only store Mainsail UI settings

VALID_USERNAME = re.compile(r"^[A-Za-z0-9._-]{2,32}$")

# =========================================================== DATABASE
LEGACY_ROLES = {"visitante": "viewer", "operador": "operator", "admin": "admin"}


def db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT NOT NULL, role TEXT NOT NULL)")
    con.execute("CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, username TEXT NOT NULL, expires REAL NOT NULL)")
    return con


def init_db():
    """Create tables and migrate data from the early Portuguese prototype, if present."""
    con = db()
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "usuarios" in tables:
            rows = con.execute("SELECT usuario, senha, papel FROM usuarios ORDER BY rowid").fetchall()
            for username, password, role in rows:
                con.execute("INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)",
                            (username, password, LEGACY_ROLES.get(role, role)))
            con.execute("DROP TABLE usuarios")
            con.execute("DROP TABLE IF EXISTS sessoes")
            con.commit()
            log.info("Migrated %d user(s) from the legacy database", len(rows))
    finally:
        con.close()


def hash_password(password):
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1)
    return f"scrypt${salt.hex()}${h.hex()}"


def check_password(password, stored):
    try:
        _, salt, h = stored.split("$")
        calc = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1)
        return hmac.compare_digest(calc.hex(), h)
    except (ValueError, TypeError):
        return False


def role_of(username):
    if username is None:
        return None
    con = db()
    try:
        row = con.execute("SELECT role FROM users WHERE username=?", (username,)).fetchone()
    finally:
        con.close()
    return row[0] if row and row[0] in ROLES else None


def primary_admin(con):
    row = con.execute("SELECT username FROM users WHERE role='admin' ORDER BY rowid LIMIT 1").fetchone()
    return row[0] if row else None


_session_cache: dict[str, tuple[str, float]] = {}


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def session_user(token):
    if not token:
        return None
    h = hash_token(token)
    now = time.time()
    hit = _session_cache.get(h)
    if hit and hit[1] > now:
        return hit[0]
    con = db()
    try:
        row = con.execute("SELECT username, expires FROM sessions WHERE token=?", (h,)).fetchone()
    finally:
        con.close()
    if not row or row[1] < now:
        _session_cache.pop(h, None)
        return None
    if len(_session_cache) > 500:
        _session_cache.clear()
    _session_cache[h] = (row[0], min(row[1], now + 30))
    return row[0]


# =========================================================== RULES
def matches(value, patterns):
    return any(fnmatch.fnmatchcase(value, p) for p in patterns)


def gcode_commands(script):
    for line in script.splitlines():
        line = line.split(";", 1)[0].strip()
        if line:
            yield line.split()[0].upper()


def blocked_gcode(role, script):
    allowed = ROLES[role]["gcode"]
    if "*" in allowed:
        return None
    for cmd in gcode_commands(script):
        if not matches(cmd, allowed):
            return cmd
    return None


def roots_allowed(role, params, keys):
    allowed = ROLES[role]["writable_roots"]
    if "*" in allowed:
        return True
    for k in keys:
        path = posixpath.normpath(str(params.get(k, "")).lstrip("/"))
        if path.startswith("..") or path.split("/", 1)[0] not in allowed:
            return False
    return True


def rpc_denial_reason(role, method, params):
    if matches(method, PUBLIC_RPC):
        return None
    if role is None:
        return "user has no role assigned"
    if not matches(method, ROLES[role]["rpc"]):
        return f"'{method}' is not allowed for role '{role}'"
    if role == "admin":
        return None
    if method in FILE_WRITE_METHODS and not roots_allowed(role, params, FILE_WRITE_METHODS[method]):
        return f"folder not allowed for role '{role}'"
    if method in ("server.database.post_item", "server.database.delete_item") \
            and params.get("namespace") not in WRITABLE_NAMESPACES:
        return f"namespace '{params.get('namespace')}' is not allowed for role '{role}'"
    if method == "printer.gcode.script":
        cmd = blocked_gcode(role, str(params.get("script", "")))
        if cmd:
            return f"G-code '{cmd}' is not allowed for role '{role}'"
    return None


# =========================================================== APP
client: httpx.AsyncClient
API_KEY = ""


def load_api_key():
    global API_KEY
    if not API_KEY and APIKEY_PATH.exists():
        API_KEY = APIKEY_PATH.read_text().strip()
    return API_KEY


@asynccontextmanager
async def lifespan(_app):
    global client
    client = httpx.AsyncClient(base_url=MOONRAKER_URL, timeout=None)
    init_db()
    if not load_api_key():
        log.error("Moonraker API key not found. Run: python main.py apikey")
    yield
    await client.aclose()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
HOP = {"host", "connection", "transfer-encoding", "keep-alive", "upgrade"}
STRIP_FROM_CLIENT = HOP | {"cookie", "authorization", "x-api-key"}


def upstream_headers(req, drop=()):
    h = {k: v for k, v in req.headers.items() if k.lower() not in STRIP_FROM_CLIENT and k.lower() not in drop}
    h["X-Api-Key"] = load_api_key()
    return h


def clean_params(query_params):
    return [(k, v) for k, v in query_params.multi_items() if k not in ("token", "access_token")]


def deny(code, msg, username, route):
    log.warning("DENIED user=%s %s: %s", username, route, msg)
    return JSONResponse({"error": {"code": code, "message": msg}}, status_code=code)


# ----------------------------------------------------------- login page
PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in</title><style>
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#121212;color:#e6e6e6;
font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.card{width:min(92vw,360px);background:#1e1e1e;border:1px solid #2c2c2c;border-radius:10px;padding:28px}
h1{margin:0 0 4px;font-size:1.25rem}
p{margin:0 0 20px;color:#9a9a9a;font-size:.9rem}
label{display:block;font-size:.85rem;color:#b5b5b5;margin:14px 0 6px}
input{width:100%;padding:10px 12px;border-radius:6px;border:1px solid #3a3a3a;background:#141414;color:#fff;font-size:1rem}
input:focus{outline:none;border-color:#d41216}
button,.button{display:block;text-align:center;text-decoration:none;margin-top:22px;width:100%;padding:11px;border:0;
border-radius:6px;background:#d41216;color:#fff;font-size:1rem;font-weight:600;cursor:pointer}
.secondary{background:#2c2c2c}
.error{margin-top:14px;padding:9px 12px;border-radius:6px;background:#3a1416;color:#ff9b9b;font-size:.9rem}
</style></head><body><div class="card">{body}</div></body></html>"""


def page(body, status=200):
    return HTMLResponse(PAGE.replace("{body}", body), status_code=status)


def login_page(error=""):
    e = f'<div class="error">{html.escape(error)}</div>' if error else ""
    return page(f"""<h1>{html.escape(LOGIN_TITLE)}</h1><p>Sign in to access the dashboard</p>
<form method="post" action="/_rbac/login">
<label for="u">Username</label><input id="u" name="username" autocomplete="username" autofocus required>
<label for="p">Password</label><input id="p" name="password" type="password" autocomplete="current-password" required>
<button type="submit">Sign in</button>{e}</form>""")


@app.get("/_rbac/auth")
async def rbac_auth(request: Request):
    """Called by nginx (auth_request) on every request."""
    if session_user(request.cookies.get(COOKIE)):
        return Response(status_code=204)
    return Response(status_code=401)


@app.get("/_rbac/login")
async def rbac_login_get(request: Request):
    username = session_user(request.cookies.get(COOKIE))
    if username:
        return page(f"""<h1>Signed in</h1><p>{html.escape(username)} · {html.escape(role_of(username) or "no role")}</p>
<a class="button" href="/">Open dashboard</a><a class="button secondary" href="/_rbac/logout">Sign out</a>""")
    return login_page()


@app.post("/_rbac/login")
async def rbac_login_post(request: Request):
    form = await request.form()
    username = str(form.get("username", "")).strip()
    password = str(form.get("password", ""))
    con = db()
    try:
        row = con.execute("SELECT password FROM users WHERE username=?", (username,)).fetchone()
    finally:
        con.close()
    if not row or not check_password(password, row[0]):
        log.warning("LOGIN FAILED user=%s ip=%s", username, request.headers.get("x-forwarded-for"))
        await asyncio.sleep(1.5)  # slows down repeated guessing
        return login_page("Invalid username or password.")
    token = secrets.token_urlsafe(32)
    now = time.time()
    con = db()
    try:
        con.execute("DELETE FROM sessions WHERE expires < ?", (now,))
        con.execute("INSERT INTO sessions VALUES (?, ?, ?)", (hash_token(token), username, now + SESSION_DAYS * 86400))
        con.commit()
    finally:
        con.close()
    log.info("LOGIN user=%s ip=%s", username, request.headers.get("x-forwarded-for"))
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax",
                    secure=SECURE_COOKIE, path="/")
    return resp


@app.get("/_rbac/logout")
async def rbac_logout(request: Request):
    token = request.cookies.get(COOKIE)
    if token:
        h = hash_token(token)
        _session_cache.pop(h, None)
        con = db()
        try:
            con.execute("DELETE FROM sessions WHERE token=?", (h,))
            con.commit()
        finally:
            con.close()
    resp = RedirectResponse("/_rbac/login", status_code=303)
    resp.delete_cookie(COOKIE, path="/")
    return resp


# ----------------------------------------------------------- user management API (Mainsail "Users" tab)
UI_JS = Path(__file__).resolve().parent / "ui.js"


def api_error(code, msg):
    return JSONResponse({"error": msg}, status_code=code)


def require_admin(request):
    username = session_user(request.cookies.get(COOKIE))
    if username is None:
        return None, api_error(401, "Not signed in.")
    if role_of(username) != "admin":
        return None, api_error(403, "Administrators only.")
    if request.method != "GET" and request.headers.get("x-rbac") != "1":
        return None, api_error(400, "Invalid request.")
    return username, None


async def json_body(request):
    try:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


@app.get("/_rbac/ui.js")
async def rbac_ui_js():
    if not UI_JS.exists():
        return Response("/* ui.js missing */", media_type="application/javascript")
    return FileResponse(UI_JS, media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/_rbac/api/me")
async def api_me(request: Request):
    username = session_user(request.cookies.get(COOKIE))
    if username is None:
        return api_error(401, "Not signed in.")
    return {"username": username, "role": role_of(username)}


@app.get("/_rbac/api/users")
async def api_list_users(request: Request):
    me, error = require_admin(request)
    if error:
        return error
    con = db()
    try:
        primary = primary_admin(con)
        rows = con.execute("SELECT username, role FROM users ORDER BY rowid").fetchall()
    finally:
        con.close()
    return {
        "roles": list(ROLES),
        "users": [{"username": u, "role": r, "primary": u == primary, "self": u == me} for u, r in rows],
    }


@app.post("/_rbac/api/users")
async def api_create_user(request: Request):
    me, error = require_admin(request)
    if error:
        return error
    data = await json_body(request)
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    role = str(data.get("role", ""))
    if not VALID_USERNAME.match(username):
        return api_error(400, "Invalid username (2 to 32 characters: letters, digits, . _ -).")
    if len(password) < 6:
        return api_error(400, "The password must have at least 6 characters.")
    if role not in ROLES:
        return api_error(400, "Invalid role.")
    con = db()
    try:
        if con.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            return api_error(409, f"User '{username}' already exists.")
        con.execute("INSERT INTO users VALUES (?, ?, ?)", (username, hash_password(password), role))
        con.commit()
    finally:
        con.close()
    log.info("USER CREATED %s (%s) by %s", username, role, me)
    return JSONResponse({"ok": True}, status_code=201)


@app.put("/_rbac/api/users/{name}/role")
async def api_change_role(name: str, request: Request):
    me, error = require_admin(request)
    if error:
        return error
    role = str((await json_body(request)).get("role", ""))
    if role not in ROLES:
        return api_error(400, "Invalid role.")
    if name == me:
        return api_error(400, "You cannot change your own role.")
    con = db()
    try:
        if name == primary_admin(con):
            return api_error(403, "The primary admin's role cannot be changed.")
        if not con.execute("UPDATE users SET role=? WHERE username=?", (role, name)).rowcount:
            return api_error(404, "User not found.")
        con.commit()
    finally:
        con.close()
    log.info("ROLE CHANGED %s -> %s by %s", name, role, me)
    return {"ok": True}


@app.delete("/_rbac/api/users/{name}")
async def api_delete_user(name: str, request: Request):
    me, error = require_admin(request)
    if error:
        return error
    if name == me:
        return api_error(400, "You cannot delete yourself.")
    con = db()
    try:
        if name == primary_admin(con):
            return api_error(403, "The primary admin cannot be deleted.")
        if not con.execute("DELETE FROM users WHERE username=?", (name,)).rowcount:
            return api_error(404, "User not found.")
        con.execute("DELETE FROM sessions WHERE username=?", (name,))
        con.commit()
    finally:
        con.close()
    _session_cache.clear()
    log.info("USER DELETED %s by %s", name, me)
    return {"ok": True}


# ----------------------------------------------------------- proxy
@app.websocket("/websocket")
async def proxy_ws(ws: WebSocket):
    username = session_user(ws.cookies.get(COOKIE))
    if username is None:
        await ws.close(code=1008)
        return
    await ws.accept()
    query = "&".join(f"{k}={v}" for k, v in clean_params(ws.query_params))
    url = MOONRAKER_WS + (f"?{query}" if query else "")
    try:
        async with websockets.connect(url, max_size=None,
                                      additional_headers={"X-Api-Key": load_api_key()}) as upstream:

            async def client_to_moonraker():
                while True:
                    raw = await ws.receive_text()
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    role = role_of(username)
                    if isinstance(msg, list):  # JSON-RPC batch: admins only
                        if role != "admin":
                            log.warning("DENIED JSON-RPC batch user=%s", username)
                            continue
                        await upstream.send(raw)
                        continue
                    method = str(msg.get("method", ""))
                    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
                    if method == "server.connection.identify" and \
                            ("access_token" in params or "api_key" in params):
                        params.pop("access_token", None)
                        params.pop("api_key", None)
                        msg["params"] = params
                        raw = json.dumps(msg)
                    reason = rpc_denial_reason(role, method, params)
                    if reason:
                        log.warning("DENIED user=%s ws %s: %s", username, method, reason)
                        if "id" in msg:
                            await ws.send_text(json.dumps({"jsonrpc": "2.0", "id": msg["id"],
                                                           "error": {"code": 403, "message": reason}}))
                        continue
                    await upstream.send(raw)

            async def moonraker_to_client():
                async for m in upstream:
                    await ws.send_text(m if isinstance(m, str) else m.decode())

            tasks = [asyncio.create_task(client_to_moonraker()), asyncio.create_task(moonraker_to_client())]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            for t in done:
                t.exception()
    except Exception as e:  # disconnections and upstream failures
        if not isinstance(e, (WebSocketDisconnect, websockets.ConnectionClosed)):
            log.warning("websocket closed: %r", e)
    finally:
        try:
            await ws.close()
        except Exception:
            pass


async def restricted_upload(request, username, role):
    route = "POST /server/files/upload"
    form = await request.form()
    root = str(form.get("root", "gcodes"))
    if not roots_allowed(role, {"root": root}, ["root"]) or ".." in str(form.get("path", "")):
        return deny(403, f"uploading to '{root}' is not allowed for role '{role}'", username, route)
    data, files = {}, []
    for k, v in form.multi_items():
        if isinstance(v, UploadFile):
            content = await v.read()
            if (v.filename or "").lower().endswith((".gcode", ".g", ".gco")):
                text = content.decode("utf-8", errors="ignore")
                forbidden = next((c for c in gcode_commands(text) if c in BLOCKED_IN_FILES), None)
                if forbidden:
                    return deny(403, f"file contains '{forbidden}', which is not allowed for role '{role}'",
                                username, route)
            files.append((k, (v.filename, content, v.content_type or "application/octet-stream")))
        else:
            data[k] = v
    r = await client.post("/server/files/upload", data=data, files=files,
                          headers=upstream_headers(request, ("content-type", "content-length")))
    return Response(r.content, r.status_code, media_type=r.headers.get("content-type"))


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_http(path: str, request: Request):
    route = f"{request.method} /{path}"
    if ".." in path:
        return deny(400, "invalid path", None, route)
    username = session_user(request.cookies.get(COOKIE))
    if username is None:
        return deny(401, "Not signed in", None, route)
    role = role_of(username)
    if role is None:
        return deny(403, "user has no role assigned", username, route)
    if not matches(route, COMMON_HTTP + ROLES[role]["http"]):
        return deny(403, f"{route} is not allowed for role '{role}'", username, route)
    if not load_api_key():
        return deny(503, "gateway has no Moonraker API key", username, route)

    if route == "POST /server/files/upload" and role != "admin":
        return await restricted_upload(request, username, role)

    body = request.stream() if request.method in ("POST", "PUT", "PATCH") else None
    req = client.build_request(request.method, "/" + path, params=clean_params(request.query_params),
                               headers=upstream_headers(request), content=body)
    r = await client.send(req, stream=True)
    return StreamingResponse(r.aiter_raw(), status_code=r.status_code,
                             headers={k: v for k, v in r.headers.items() if k.lower() not in HOP},
                             background=BackgroundTask(r.aclose))


# =========================================================== CLI
def ask_password():
    while True:
        p1 = getpass.getpass("Password: ")
        if len(p1) < 6:
            print("Use at least 6 characters.")
            continue
        if p1 != getpass.getpass("Repeat password: "):
            print("Passwords do not match.")
            continue
        return p1


def cli_apikey():
    with httpx.Client(base_url=MOONRAKER_URL) as c:
        # Works without credentials while this machine is still a Moonraker trusted client.
        r = c.get("/access/api_key")
        if r.status_code != 200:
            print("This machine is not a Moonraker trusted client; sign in with a Moonraker user.")
            user = input("Moonraker username: ").strip()
            password = getpass.getpass("Moonraker password: ")
            r = c.post("/access/login", json={"username": user, "password": password})
            if r.status_code != 200:
                print("Moonraker login failed:", r.text[:200])
                return
            token = r.json()["result"]["token"]
            r = c.get("/access/api_key", headers={"Authorization": f"Bearer {token}"})
        if r.status_code != 200:
            print("Could not read the API key:", r.text[:200])
            return
        key = r.json()["result"]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    APIKEY_PATH.write_text(key)
    os.chmod(APIKEY_PATH, 0o600)
    print(f"API key saved to {APIKEY_PATH}")


if __name__ == "__main__":
    args = sys.argv[1:]
    cmd = args[0] if args else ""
    init_db()
    con = db()
    try:
        if cmd == "apikey":
            cli_apikey()
        elif cmd in ("role", "remove") and len(args) >= 2 and args[1] == primary_admin(con):
            print(f"{args[1]} is the primary admin: its role cannot be changed and it cannot be removed.")
        elif cmd == "create" and len(args) == 3 and args[2] in ROLES:
            if not VALID_USERNAME.match(args[1]):
                print("Invalid username (2 to 32 characters: letters, digits, . _ -).")
            elif con.execute("SELECT 1 FROM users WHERE username=?", (args[1],)).fetchone():
                print("User already exists.")
            else:
                con.execute("INSERT INTO users VALUES (?, ?, ?)", (args[1], hash_password(ask_password()), args[2]))
                con.commit()
                print(f"{args[1]} created as {args[2]}")
        elif cmd == "passwd" and len(args) == 2:
            if not con.execute("SELECT 1 FROM users WHERE username=?", (args[1],)).fetchone():
                print("User does not exist.")
            else:
                con.execute("UPDATE users SET password=? WHERE username=?", (hash_password(ask_password()), args[1]))
                con.execute("DELETE FROM sessions WHERE username=?", (args[1],))
                con.commit()
                print("Password changed (this user's open sessions were signed out).")
        elif cmd == "role" and len(args) == 3 and args[2] in ROLES:
            n = con.execute("UPDATE users SET role=? WHERE username=?", (args[2], args[1])).rowcount
            con.commit()
            print(f"{args[1]} -> {args[2]}" if n else "User does not exist.")
        elif cmd == "remove" and len(args) == 2:
            con.execute("DELETE FROM users WHERE username=?", (args[1],))
            con.execute("DELETE FROM sessions WHERE username=?", (args[1],))
            con.commit()
            print(f"{args[1]} removed")
        elif cmd == "list":
            primary = primary_admin(con)
            for u, r in con.execute("SELECT username, role FROM users ORDER BY rowid"):
                print(f"{u:20} {r}" + ("   (primary admin)" if u == primary else ""))
        else:
            print(__doc__)
    finally:
        con.close()
