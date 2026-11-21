"""Render-only adapter: public HTTPS edge, private demo credentials, ephemeral SQLite.

Start on Render with: python -m emobility.cloud_server
This is a controlled academic simulator, not an authenticated production deployment.
"""
from __future__ import annotations

import logging
import os
import threading
from urllib.parse import urlsplit

from .domain import ACTOR_ROLES, Service
from .server import AppServer, Handler, LOG


class CloudHandler(Handler):
    def valid_host(self):
        public_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").lower().strip()
        return bool(public_host) and self.headers.get("Host", "").lower() == public_host

    def do_POST(self):
        # TLS terminates at Render; the upstream HTTP adapter assumes local HTTP.
        host = self.headers.get("Host", "")
        if not self.valid_host() or self.headers.get("Origin") != f"https://{host}":
            return self.reject(403, "ORIGIN", "HTTPS same-origin request required.")
        self.headers.replace_header("Origin", f"http://{host}")
        return super().do_POST()

    def respond(self, status, body, content_type="application/json; charset=utf-8", cookie=None):
        if cookie:
            cookie = cookie + "; Secure"
        return super().respond(status, body, content_type, cookie)


def main():
    public_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")
    if not public_host or not public_host.endswith(".onrender.com"):
        raise SystemExit("Render hostname is required; refusing to open a public listener.")
    missing = [user for user in ACTOR_ROLES if not os.environ.get(f"EMOBILITY_{user.upper()}_PASSWORD")]
    if missing:
        raise SystemExit("Private credentials are required for ALL demo accounts: " + ", ".join(missing))
    port = int(os.environ.get("PORT", "10000"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = AppServer(("0.0.0.0", port), Service("data/hub.sqlite", simulator=True))
    server.RequestHandlerClass = CloudHandler

    def maintain():
        while not server.stopping.wait(5):
            try:
                server.service.tick()
            except Exception:
                LOG.exception("Maintenance tick failed")

    threading.Thread(target=maintain, daemon=True, name="expiry-maintenance").start()
    print(f"Smart E-Mobility private academic demo at https://{public_host}", flush=True)
    print("Synthetic device evidence only; local SQLite is EPHEMERAL on free Render.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.stopping.set()
        server.server_close()


if __name__ == "__main__":
    main()
