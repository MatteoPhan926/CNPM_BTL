"""Loopback HTTP adapter for the A/B/C/D demonstration.

Run: python -m emobility.server --simulator
The deliberately local demo accounts are not a production identity provider.
"""
from __future__ import annotations

import argparse
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import parse_qs, urlsplit

from .domain import ACTOR_ROLES, DomainError, Service


WEB_ROOT = Path(__file__).resolve().parent.parent / "web"
LOG = logging.getLogger("emobility")


class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, service):
        super().__init__(address, Handler)
        self.service = service
        self.sessions = {}
        self.auth_lock = threading.Lock()
        self.login_attempts = {}
        self.credentials = {}
        for username in ACTOR_ROLES:
            password = os.environ.get(f"EMOBILITY_{username.upper()}_PASSWORD", f"{username}-demo")
            salt = secrets.token_bytes(16)
            digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
            self.credentials[username] = (salt, digest)
        self.stopping = threading.Event()

    def close(self):
        self.stopping.set()
        self.shutdown()
        self.server_close()


class Handler(BaseHTTPRequestHandler):
    server_version = "SmartEMobility/1"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, fmt, *args):
        LOG.info("%s %s", self.client_address[0], fmt % args)

    def respond(self, status, body, content_type="application/json; charset=utf-8", cookie=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # The committed operation can be recovered with the same intent.

    def reject(self, status, code, message):
        self.respond(status, {"error": {"code": code, "message": message}})

    def valid_host(self):
        port = self.server.server_address[1]
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if port == 80:
            allowed |= {"127.0.0.1", "localhost"}
        return self.headers.get("Host", "") in allowed

    def actor(self):
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
            token = cookies.get("emobility_session")
            token = token.value if token else ""
        except Exception:
            token = ""
        with self.server.auth_lock:
            session = self.server.sessions.get(token)
            if not session or session[1] < time.time():
                self.server.sessions.pop(token, None)
                return None
            return dict(session[0])

    def do_GET(self):
        if not self.valid_host():
            return self.reject(403, "HOST", "Use the local server address.")
        path = urlsplit(self.path).path
        if path == "/api/health":
            return self.respond(200, {"status": "ok", "simulator": self.server.service.simulator})
        if path == "/api/state":
            actor = self.actor()
            if not actor:
                return self.reject(401, "AUTH_REQUIRED", "Sign in to continue.")
            try:
                data = self.server.service.snapshot(actor)
                data["actor"] = actor
                return self.respond(200, data)
            except Exception:
                LOG.exception("Snapshot failed")
                return self.reject(500, "INTERNAL", "Unable to load current state.")
        if path == "/api/rental-qr":
            actor = self.actor()
            if not actor:
                return self.reject(401, "AUTH_REQUIRED", "Sign in to continue.")
            try:
                hold_id = parse_qs(urlsplit(self.path).query).get('hold_id', [None])[0]
                return self.respond(200, self.server.service.rental_qr(actor, hold_id))
            except DomainError as exc:
                return self.reject(exc.status, exc.code, exc.message)
            except Exception:
                LOG.exception('Rental QR could not be rendered')
                return self.reject(500, 'INTERNAL', 'Unable to load rental QR.')
        if path == "/api/charging-qr":
            actor = self.actor()
            if not actor:
                return self.reject(401, "AUTH_REQUIRED", "Sign in to continue.")
            try:
                request_id = parse_qs(urlsplit(self.path).query).get('request_id', [None])[0]
                return self.respond(200, self.server.service.charging_qr(actor, request_id))
            except DomainError as exc:
                return self.reject(exc.status, exc.code, exc.message)
            except Exception:
                LOG.exception('Charging QR could not be rendered')
                return self.reject(500, 'INTERNAL', 'Unable to load charging QR.')
        if path == "/api/parking-qr":
            actor = self.actor()
            if not actor:
                return self.reject(401, "AUTH_REQUIRED", "Sign in to continue.")
            try:
                right_id = parse_qs(urlsplit(self.path).query).get('right_id', [None])[0]
                return self.respond(200, self.server.service.parking_qr(actor, right_id))
            except DomainError as exc:
                return self.reject(exc.status, exc.code, exc.message)
            except Exception:
                LOG.exception('Parking QR could not be rendered')
                return self.reject(500, 'INTERNAL', 'Unable to load parking QR.')
        resources = {"/": ("index.html", "text/html; charset=utf-8"),
                     "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                     "/network.js": ("network.js", "text/javascript; charset=utf-8"),
                     "/parking-qr.js": ("parking-qr.js", "text/javascript; charset=utf-8"),
                     "/service-bookings.js": ("service-bookings.js", "text/javascript; charset=utf-8"),
                     "/styles.css": ("styles.css", "text/css; charset=utf-8")}
        resource = resources.get(path)
        if not resource:
            return self.reject(404, "NOT_FOUND", "Not found.")
        try:
            self.respond(200, (WEB_ROOT / resource[0]).read_bytes(), resource[1])
        except OSError:
            self.reject(404, "NOT_FOUND", "Application asset is unavailable.")

    def do_POST(self):
        if not self.valid_host():
            return self.reject(403, "HOST", "Use the local server address.")
        if self.headers.get("Origin") != f"http://{self.headers.get('Host')}":
            return self.reject(403, "ORIGIN", "A matching same-origin request is required.")
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self.reject(415, "CONTENT_TYPE", "Send application/json.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536:
                return self.reject(413, "BODY_SIZE", "Request body must be between 1 and 65536 bytes.")
            raw = self.rfile.read(length)
            if len(raw) != length:
                return self.reject(400, "JSON", "Incomplete request body.")
            data = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            if not isinstance(data, dict):
                raise ValueError("Expected an object")
        except (ValueError, UnicodeDecodeError):
            return self.reject(400, "JSON", "Send a valid JSON object with finite numbers.")
        path = urlsplit(self.path).path
        if path == "/api/login":
            return self.login(data)
        actor = self.actor()
        if not actor:
            return self.reject(401, "AUTH_REQUIRED", "Sign in to continue.")
        if path == "/api/logout":
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            token = cookies.get("emobility_session")
            if token:
                with self.server.auth_lock:
                    self.server.sessions.pop(token.value, None)
            return self.respond(200, {"status": "SIGNED_OUT"}, cookie="emobility_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
        if path != "/api/commands":
            return self.reject(404, "NOT_FOUND", "Not found.")
        action, payload, intent = data.get("action"), data.get("payload"), data.get("intent_id")
        if not isinstance(action, str) or not isinstance(payload, dict) or not isinstance(intent, str) or not 8 <= len(intent) <= 128:
            return self.reject(400, "COMMAND", "Provide action, payload object and an intent_id of 8–128 characters.")
        try:
            result = self.server.service.command(actor, action, payload, intent)
            self.respond(200, result)
        except DomainError as exc:
            self.reject(exc.status, exc.code, str(exc))
        except Exception:
            LOG.exception("Command failed: %s", action)
            self.reject(500, "INTERNAL", "Outcome uncertain. Retry the identical intent; do not submit a new request.")

    def login(self, data):
        username, password = data.get("username"), data.get("password")
        if not isinstance(username, str) or not isinstance(password, str) or len(password) > 200:
            return self.reject(400, "LOGIN", "Enter a username and password.")
        now = time.time()
        address = self.client_address[0]
        with self.server.auth_lock:
            attempts = [at for at in self.server.login_attempts.get(address, []) if at > now - 60]
            self.server.login_attempts[address] = attempts
            if len(attempts) >= 20:
                return self.reject(429, "RATE_LIMIT", "Too many attempts. Try again in one minute.")
            attempts.append(now)
        credential = self.server.credentials.get(username)
        salt, expected = credential or (b"invalid-account!", b"\0" * 32)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
        if not credential or not hmac.compare_digest(actual, expected):
            return self.reject(401, "LOGIN", "Incorrect username or password.")
        actor = {"id": username, "role": ACTOR_ROLES[username]}
        token = secrets.token_urlsafe(32)
        with self.server.auth_lock:
            self.server.sessions = {key: value for key, value in self.server.sessions.items() if value[1] >= now}
            self.server.sessions[token] = (actor, now + 8 * 3600)
        self.respond(200, {"actor": actor}, cookie=f"emobility_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800")


def create_server(db_path="data/hub.sqlite", simulator=False, host="127.0.0.1", port=8000):
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError("This demo server accepts loopback binding only.")
    return AppServer((host, port), Service(db_path, simulator=simulator))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/hub.sqlite")
    parser.add_argument("--host", choices=("127.0.0.1", "localhost"), default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--simulator", action="store_true", help="Enable explicit operator-only synthetic evidence controls; no real IoT.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = create_server(args.db, args.simulator, args.host, args.port)

    def maintain():
        while not server.stopping.wait(5):
            try:
                server.service.tick()
            except Exception:
                LOG.exception("Maintenance tick failed")

    threading.Thread(target=maintain, daemon=True, name="expiry-maintenance").start()
    print(f"Smart E-Mobility: http://{args.host}:{server.server_port}", flush=True)
    print(f"Controlled simulator: {'ENABLED — synthetic evidence only' if args.simulator else 'disabled; physical actions remain pending'}", flush=True)
    print(f"Demo accounts: {', '.join(ACTOR_ROLES)} (default password: <username>-demo).", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.stopping.set()
        server.server_close()


if __name__ == "__main__":
    main()
