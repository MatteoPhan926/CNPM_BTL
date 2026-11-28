"""Exercise the Render adapter on loopback, including its synthetic heartbeat."""
from http.client import HTTPConnection
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from emobility.cloud_server import create_cloud_server
from emobility.domain import ACTOR_ROLES, POLICY
from emobility.server import serve


PUBLIC_HOST = "demo.onrender.com"


class CloudServerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.database = Path(tmp.name) / "demo.sqlite"
        self.env = {f"EMOBILITY_{user.upper()}_PASSWORD": f"private-{user}" for user in ACTOR_ROLES}
        self.env.update(RENDER_EXTERNAL_HOSTNAME=PUBLIC_HOST, PORT="0")

    def create(self, env):
        with patch.dict(os.environ, env, clear=True):
            return create_cloud_server(db_path=self.database, host="127.0.0.1")

    def test_startup_requires_render_host_and_all_private_credentials(self):
        required = {"RENDER_EXTERNAL_HOSTNAME": "Render hostname"}
        required.update({f"EMOBILITY_{user.upper()}_PASSWORD": user for user in ACTOR_ROLES})
        for key, message in required.items():
            with self.subTest(missing=key):
                settings = self.env.copy()
                del settings[key]
                with self.assertRaisesRegex(SystemExit, message):
                    self.create(settings)
                self.assertFalse(self.database.exists())

    def test_render_login_state_and_refresh_of_stale_simulated_fleet(self):
        server = self.create(self.env)
        self.addCleanup(server.server_close)
        student = {"id": "alice", "role": "student"}
        future = server.service.clock() + POLICY["freshness"] + 1
        server.service.clock = lambda: future
        stale_state = server.service.snapshot(student)
        self.assertFalse(any(v["available"] for v in stale_state["vehicles"]))

        thread = threading.Thread(target=serve, args=(server,), kwargs={"auto_refresh": True})
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)

        def request(method, path, headers=None, data=None):
            headers = {"Host": PUBLIC_HOST, **(headers or {})}
            conn = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            try:
                conn.request(method, path, headers=headers, body=json.dumps(data) if data else None)
                res = conn.getresponse()
                return res.status, res.getheader("Set-Cookie"), json.loads(res.read())
            finally:
                conn.close()

        status, _, health = request("GET", "/api/health")
        self.assertEqual((status, health), (200, {"status": "ok", "simulator": True}))
        self.assertEqual(request("GET", "/api/health", {"Host": "localhost"})[0], 403)
        login = {"username": "alice", "password": self.env["EMOBILITY_ALICE_PASSWORD"]}
        headers = {"Content-Type": "application/json", "Origin": "http://" + PUBLIC_HOST}
        self.assertEqual(request("POST", "/api/login", headers, login)[0], 403)
        headers["Origin"] = "https://" + PUBLIC_HOST
        status, cookie, _ = request("POST", "/api/login", headers, login)
        self.assertEqual(status, 200)
        session = SimpleCookie(cookie)["emobility_session"]
        self.assertTrue(session["secure"])
        self.assertTrue(session["httponly"])
        status, _, state = request("GET", "/api/state", {"Cookie": "emobility_session=" + session.value})
        self.assertEqual(status, 200)
        self.assertEqual(state["actor"], student)
        vehicle = next(v for v in state["vehicles"] if v["id"] == "V1")
        self.assertTrue(vehicle["available"])
        self.assertEqual((vehicle["freshness"], vehicle["evidence"]), ("FRESH", "SIMULATED"))
        self.assertEqual(state["trips"], [])
