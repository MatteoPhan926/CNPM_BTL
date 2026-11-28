"""Render-only adapter: public HTTPS edge, private demo credentials, ephemeral SQLite.

Start on Render with: python -m emobility.cloud_server --auto-refresh
This is a controlled academic simulator, not an authenticated production deployment.
"""
from __future__ import annotations

import argparse
import logging
import os

from .domain import ACTOR_ROLES, Service
from .server import AppServer, Handler, serve


class CloudHandler(Handler):
    def valid_host(self):
        return self.headers.get("Host", "").lower() == self.server.public_host.lower()

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


def create_cloud_server(db_path="data/hub.sqlite", host="0.0.0.0"):
    public_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")
    if not public_host or not public_host.endswith(".onrender.com"):
        raise SystemExit("Render hostname is required; refusing to open a public listener.")
    missing = [user for user in ACTOR_ROLES if not os.environ.get(f"EMOBILITY_{user.upper()}_PASSWORD")]
    if missing:
        raise SystemExit("Private credentials are required for ALL demo accounts: " + ", ".join(missing))
    port = int(os.environ.get("PORT", "10000"))
    server = AppServer((host, port), Service(db_path, simulator=True))
    server.RequestHandlerClass = CloudHandler
    server.public_host = public_host
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auto-refresh", action="store_true",
                        help="Refresh existing simulated sensor observations every 30 seconds.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = create_cloud_server()
    print(f"Smart E-Mobility private academic demo at https://{server.public_host}", flush=True)
    print("Synthetic device evidence only; local SQLite is EPHEMERAL on free Render.", flush=True)
    serve(server, auto_refresh=args.auto_refresh)


if __name__ == "__main__":
    main()
