"""Cross-role journeys through the same HTTP entry points used by the web UI."""
import json
from http.client import HTTPConnection
from pathlib import Path
import tempfile
import threading
import unittest
from uuid import uuid4

from emobility.server import create_server


class HttpIntegrationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.database = Path(temp.name) / "demo.sqlite"
        self.start_server()

    def start_server(self):
        self.server = create_server(self.database, simulator=True, port=0)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.close)
        self.cookies = {}

    def api(self, path, actor=None, data=None, status=200):
        port = self.server.server_port
        headers = {"Origin": f"http://127.0.0.1:{port}", "Content-Type": "application/json"}
        if actor in self.cookies:
            headers["Cookie"] = self.cookies[actor]
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request("GET" if data is None else "POST", path, headers=headers,
                         body=json.dumps(data) if data is not None else None)
            response = conn.getresponse()
            result = json.loads(response.read())
            self.assertEqual(response.status, status, result)
            if response.getheader("Set-Cookie"):
                self.cookies[actor] = response.getheader("Set-Cookie").split(";")[0]
            return result
        finally:
            conn.close()

    def login(self, actor):
        reply = self.api("/api/login", actor, {"username": actor, "password": actor + "-demo"})
        self.assertEqual(reply["actor"]["id"], actor)

    def command(self, actor, action, payload, status=200):
        reply = self.api("/api/commands", actor, {"action": action, "payload": payload,
                         "intent_id": uuid4().hex}, status=status)
        return reply.get("record", reply)

    def test_staff_login_handoff_and_shared_rental_availability(self):
        self.api("/api/state", status=401)
        for actor in ("alice", "dispatcher", "operator", "technician"):
            self.login(actor)
        draft = dict(source_hub_id="H1", dest_hub_id="H2", staff_id="dispatcher", vehicle_ids=["V1"])
        self.command("alice", "transfer_preview", draft, 403)
        order = self.command("operator", "transfer_preview", draft)
        reference = {"order_id": order["id"]}
        self.command("operator", "transfer_issue", reference)
        self.command("technician", "transfer_start", reference, 403)
        self.command("dispatcher", "transfer_start", reference)
        self.command("dispatcher", "transfer_handover", dict(reference, vehicle_ids=["V1"]))
        self.command("alice", "reserve_vehicle", {"vehicle_id": "V1"}, 409)
        op = self.api("/api/state", "operator")
        cmd = next(c for c in op["commands"] if c["kind"] == "TRANSFER")
        self.assertEqual(self.command("operator", "simulate", {"command_id": cmd["id"]})["status"],
                         "ACKNOWLEDGED")
        student = self.api("/api/state", "alice")
        vehicle = next(v for v in student["vehicles"] if v["id"] == "V1")
        self.assertEqual(vehicle["hub_id"], "H2")
        self.assertTrue(vehicle["available"])
        self.command("alice", "reserve_vehicle", {"vehicle_id": "V1"})
        self.api("/api/logout", "dispatcher", {})
        self.api("/api/state", "dispatcher", status=401)

    def test_parking_qr_authentication_and_checkin_boundary(self):
        self.api('/api/parking-qr?right_id=unknown', status=401)
        for actor in ('alice', 'bob', 'operator'):
            self.login(actor)
        now = self.api('/api/state', 'alice')['now']
        right = self.command('alice', 'reserve_parking', dict(vehicle_id='P1', hub_id='H2', start=now, end=now+3600))
        route = '/api/parking-qr?right_id=' + right['id']
        self.api(route, 'bob', status=403)
        qr = self.api(route, 'alice')
        self.assertTrue(qr['usable'])
        self.assertEqual(qr['token'], right['qr']['token'])
        self.command('alice', 'arrive', dict(right_id=right['id']), 400)
        self.command('alice', 'arrive', dict(qr_token=qr['token']))
        pending = self.api('/api/state', 'alice')
        self.assertEqual(next(s for s in pending['spots'] if s['id']==right['spot_id'])['state'], 'EMPTY')
        self.assertFalse(self.api(route, 'alice')['usable'])
        cmd = next(c for c in self.api('/api/state', 'operator')['commands'] if c['kind']=='ARRIVAL')
        self.command('operator', 'simulate', dict(command_id=cmd['id']))
        self.assertEqual(self.api(route, 'alice')['status'], 'CONSUMED')
        self.command('alice', 'arrive', dict(qr_token=qr['token']), 409)
        self.assertEqual(len(self.api('/api/state', 'alice')['visits']), 1)

    def test_charging_only_approval_and_qr_http_contract(self):
        self.api('/api/charging-qr?request_id=unknown', status=401)
        for actor in ('alice', 'bob', 'operator'):
            self.login(actor)
        now = self.api('/api/state', 'alice')['now']
        request = self.command('alice', 'submit_charge_request', dict(
            vehicle_id='P1', hub_id='H1', declared_soc=20, target_soc=80, arrival_time=now))
        self.assertEqual(request['status'], 'PENDING')
        reference = dict(request_id=request['id'])
        route = '/api/charging-qr?request_id=' + request['id']
        self.api(route, 'alice', status=404)
        self.command('alice', 'approve_charge_request', reference, 403)
        booked = self.command('operator', 'approve_charge_request', reference)
        self.assertEqual(booked['status'], 'BOOKED')
        qr = self.api(route, 'alice')
        self.assertIn('<svg', qr['svg'])
        self.api(route, 'bob', status=403)
        self.assertEqual(self.api('/api/state', 'bob')['charge_requests'], [])
        payload = dict(reference, qr_token=qr['token'])
        self.command('bob', 'scan_charge', payload, 403)
        self.command('alice', 'scan_charge', payload)
        self.command('alice', 'scan_charge', payload)
        state = self.api('/api/state', 'operator')
        commands = [c for c in state['commands'] if c['kind']=='ARRIVAL']
        self.assertEqual(len(commands), 1)
        self.assertEqual(next(s for s in state['spots'] if s['id']==booked['spot_id'])['state'], 'EMPTY')
        self.command('operator', 'simulate', dict(command_id=commands[0]['id']))
        self.assertEqual(self.api(route, 'alice')['status'], 'CONSUMED')
        self.assertEqual(len(self.api('/api/state', 'alice')['visits']), 1)

    def test_rental_qr_http_contract(self):
        self.api('/api/rental-qr?hold_id=unknown', status=401)
        for actor in ('alice', 'bob', 'operator'):
            self.login(actor)
        hold = self.command('alice', 'reserve_vehicle', dict(vehicle_id='V1'))
        route = '/api/rental-qr?hold_id=' + hold['id']
        qr = self.api(route, 'alice')
        self.assertTrue(qr['usable'])
        self.api(route, 'bob', status=403)
        payload = dict(hold_id=hold['id'], qr_token=qr['token'])
        self.command('bob', 'scan_rental', payload, 403)
        self.command('alice', 'scan_rental', payload)
        self.command('alice', 'scan_rental', payload)
        state = self.api('/api/state', 'operator')
        commands = [c for c in state['commands'] if c['kind']=='PICKUP']
        self.assertEqual(len(commands), 1)
        self.assertEqual(self.api('/api/state', 'alice')['trips'], [])
        self.command('operator', 'simulate', dict(command_id=commands[0]['id']))
        self.assertFalse(self.api(route, 'alice')['usable'])
        self.assertEqual(len(self.api('/api/state', 'alice')['trips']), 1)

    def test_charger_ticket_changes_customer_booking_and_survives_restart(self):
        for actor in ("alice", "operator", "technician"):
            self.login(actor)
        ticket = self.command("operator", "d_open_incident",
                              {"resource_id": "H2-C1", "message": "Connector casing damaged"})
        start = self.api("/api/state", "alice")["now"] + 60
        booking = dict(vehicle_id="P1", hub_id="H2", spot_id="H2-S1", charging=True,
                       target_soc=70, start=start, end=start + 3600)
        self.command("alice", "reserve_parking", booking, 409)
        repair = dict(incident_id=ticket["id"], outcome="RESOLVED",
                      note="Replaced casing and completed inspection", safety_passed=True)
        self.command("technician", "d_update_incident", repair)
        self.command("alice", "reserve_parking", booking)
        self.server.close()
        self.start_server()
        self.login("alice")
        state = self.api("/api/state", "alice")
        self.assertEqual(len(state["rights"]), 1)
        self.assertEqual(state["sessions"][0]["right_id"], state["rights"][0]["id"])
