"""Requirement-driven adversarial checks through the domain's public API.

These use an injected clock and independent database connections, never direct
database mutations. Physical outcomes are explicitly simulated, not IoT proof.
"""
import concurrent.futures
import tempfile
import threading
import unittest
import uuid
from pathlib import Path

from emobility.domain import DomainError, Service


ALICE = {"id": "alice", "role": "student"}
BOB = {"id": "bob", "role": "student"}
OP = {"id": "operator", "role": "operator"}


class Clock:
    def __init__(self):
        self.value = 1_800_000_000.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class AdversarialDomainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / "hub.sqlite")
        self.clock = Clock()
        self.service = Service(self.db, simulator=True, clock=self.clock)

    def command(self, action, payload=None, actor=ALICE, intent=None, service=None):
        return (service or self.service).command(
            actor, action, payload or {}, intent or uuid.uuid4().hex
        )

    def state(self, actor=OP):
        return self.service.snapshot(actor)

    def rows(self, kind, actor=OP):
        return self.state(actor)[kind]

    def row(self, kind, identifier):
        return next(r for r in self.rows(kind) if r["id"] == identifier)

    def create(self, kind, action, payload=None, actor=ALICE):
        before = {r["id"] for r in self.rows(kind)}
        self.command(action, payload, actor)
        added = [r for r in self.rows(kind) if r["id"] not in before]
        self.assertEqual(len(added), 1, f"Expected one new {kind}: {added}")
        return added[0]

    def hold(self, actor=ALICE, vehicle="V1"):
        return self.create("holds", "reserve_vehicle", {"vehicle_id": vehicle}, actor)

    def parking(self, actor=ALICE, vehicle="P1", charging=False, **extra):
        payload = {
            "vehicle_id": vehicle,
            "hub_id": "H2",
            "start": self.clock(),
            "end": self.clock() + 3600,
            "charging": charging,
            "target_soc": 60,
        }
        payload.update(extra)
        return self.create("rights", "reserve_parking", payload, actor)

    def pending(self, action, payload, actor=ALICE):
        before = {r["id"] for r in self.rows("commands")}
        self.command(action, payload, actor)
        commands = [r for r in self.rows("commands") if r["id"] not in before]
        self.assertEqual(len(commands), 1, commands)
        return commands[0]

    def acknowledge(self, command, **extra):
        payload = {"command_id": command["id"], "event_id": uuid.uuid4().hex}
        payload.update(extra)
        return self.command("simulate", payload, OP)

    def trip(self):
        hold = self.hold()
        command = self.pending("pickup", {"hold_id": hold["id"]})
        self.acknowledge(command)
        return next(t for t in self.rows("trips") if t["vehicle_id"] == "V1")

    def charge_ready(self):
        right = self.parking(charging=True)
        session = next(s for s in self.rows("sessions") if s["right_id"] == right["id"])
        self.acknowledge(self.pending("arrive", {"right_id": right["id"]}))
        self.acknowledge(self.pending("plug", {"session_id": session["id"]}))
        return right, session

    def test_last_vehicle_race_has_one_winner_across_connections(self):
        barrier = threading.Barrier(2)

        def reserve(actor):
            connection = Service(self.db, simulator=True, clock=self.clock)
            barrier.wait()
            try:
                self.command("reserve_vehicle", {"vehicle_id": "V1"}, actor,
                             service=connection)
                return "won"
            except DomainError:
                return "conflict"

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(reserve, [ALICE, BOB]))
        self.assertCountEqual(outcomes, ["won", "conflict"])
        holds = [h for h in self.rows("holds") if h["vehicle_id"] == "V1"]
        self.assertEqual(len(holds), 1)

    def test_one_student_cannot_hold_two_vehicles(self):
        self.hold()
        with self.assertRaises(DomainError):
            self.hold(vehicle="V2")
        self.assertEqual(len(self.rows("holds")), 1)

    def test_receipt_replay_survives_restart_and_payload_collision_fails(self):
        intent = "reservation-retry-after-lost-response"
        first = self.command("reserve_vehicle", {"vehicle_id": "V1"}, intent=intent)
        self.service = Service(self.db, simulator=True, clock=self.clock)
        replay = self.command("reserve_vehicle", {"vehicle_id": "V1"}, intent=intent)
        self.assertEqual(first, replay)
        self.assertEqual(len(self.rows("holds")), 1)
        with self.assertRaises(DomainError):
            self.command("reserve_vehicle", {"vehicle_id": "V2"}, intent=intent)

    def test_ownership_on_cancel_and_history(self):
        hold = self.hold()
        with self.assertRaises(DomainError):
            self.command("cancel_hold", {"hold_id": hold["id"]}, BOB)
        self.assertNotIn(hold["id"], {r["id"] for r in self.rows("holds", BOB)})
        self.assertEqual(self.row("holds", hold["id"])["status"], "ACTIVE")

    def test_personal_vehicle_owner_cannot_be_forged_in_payload(self):
        with self.assertRaises(DomainError):
            self.command("reserve_parking", {"vehicle_id": "P1", "owner_id": "alice",
                                             "hub_id": "H2", "start": self.clock(),
                                             "end": self.clock() + 3600}, BOB)
        self.assertEqual(len(self.rows("rights")), 0)

    def test_cancel_hold_releases_only_its_unused_dependent_right(self):
        hold = self.hold()
        dependent = self.parking(vehicle="V1", hold_id=hold["id"], start=self.clock() + 300,
                                 end=self.clock() + 3600)
        independent = self.parking()
        self.command("cancel_hold", {"hold_id": hold["id"]})
        self.assertEqual(self.row("rights", dependent["id"])["status"], "CANCELLED")
        self.assertEqual(self.row("rights", independent["id"])["status"], "CONFIRMED")

    def test_student_cannot_forge_simulator_event(self):
        hold = self.hold()
        command = self.pending("pickup", {"hold_id": hold["id"]})
        with self.assertRaises(DomainError):
            self.command("simulate", {"command_id": command["id"]})
        self.assertEqual(len(self.rows("trips")), 0)

    def test_non_simulator_mode_does_not_accept_simulated_evidence(self):
        service = Service(str(Path(self.tmp.name) / "no-simulator.sqlite"),
                          simulator=False, clock=self.clock)
        with self.assertRaises(DomainError):
            self.command("sim_refresh", actor=OP, service=service)

    def test_pickup_click_never_opens_trip_or_releases_bay(self):
        hold = self.hold()
        before = self.state()
        self.pending("pickup", {"hold_id": hold["id"]})
        after = self.state()
        self.assertEqual(len(after["trips"]), 0)
        occupied_before = {(s["id"], s.get("vehicle_id")) for s in before["spots"]
                           if s["state"] == "OCCUPIED"}
        occupied_after = {(s["id"], s.get("vehicle_id")) for s in after["spots"]
                          if s["state"] == "OCCUPIED"}
        self.assertEqual(occupied_before, occupied_after)
        with self.assertRaises(DomainError):
            self.command("cancel_hold", {"hold_id": hold["id"]})

    def test_unknown_pickup_blocks_reallocation_after_hold_expiry(self):
        hold = self.hold()
        command = self.pending("pickup", {"hold_id": hold["id"]})
        self.acknowledge(command, outcome="UNKNOWN")
        self.clock.advance(601)
        self.service.tick()
        self.command("sim_refresh", actor=OP)
        with self.assertRaises(DomainError):
            self.command("reserve_vehicle", {"vehicle_id": "V1"}, BOB)
        self.assertEqual(self.row("holds", hold["id"])["status"], "HANDOVER_PENDING")
        self.assertEqual(len(self.rows("trips")), 0)
        self.assertTrue(self.rows("incidents"), "Uncertain handover needs a durable escalation")

    def test_cancel_pickup_race_has_one_valid_transition(self):
        hold = self.hold()
        barrier = threading.Barrier(2)

        def perform(action):
            service = Service(self.db, simulator=True, clock=self.clock)
            barrier.wait()
            try:
                self.command(action, {"hold_id": hold["id"]}, service=service)
                return action
            except DomainError:
                return "conflict"

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(perform, ["cancel_hold", "pickup"]))
        self.assertEqual(results.count("conflict"), 1)
        self.assertIn(self.row("holds", hold["id"])["status"],
                      ["CANCELLED", "HANDOVER_PENDING"])

    def test_duplicate_physical_event_opens_exactly_one_trip(self):
        hold = self.hold()
        command = self.pending("pickup", {"hold_id": hold["id"]})
        payload = {"command_id": command["id"], "event_id": "same-physical-departure"}
        self.command("simulate", payload, OP)
        self.command("simulate", payload, OP)
        self.assertEqual(len(self.rows("trips")), 1)
        self.assertEqual(self.row("holds", hold["id"])["status"], "CONSUMED")

    def test_event_identity_cannot_be_reused_with_different_payload(self):
        hold = self.hold()
        command = self.pending("pickup", {"hold_id": hold["id"]})
        payload = {"command_id": command["id"], "event_id": "immutable-event", "outcome": "ACK"}
        self.command("simulate", payload, OP)
        payload["outcome"] = "REJECT"
        with self.assertRaises(DomainError):
            self.command("simulate", payload, OP)
        self.assertEqual(len(self.rows("trips")), 1)

    def test_stale_physical_event_cannot_confirm_pickup(self):
        hold = self.hold()
        command = self.pending("pickup", {"hold_id": hold["id"]})
        try:
            self.acknowledge(command, observed_at=self.clock() - 91)
        except DomainError:
            pass
        self.assertEqual(len(self.rows("trips")), 0)
        self.assertEqual(self.row("holds", hold["id"])["status"], "HANDOVER_PENDING")

    def test_trip_return_requires_evidence_then_persists_across_restart(self):
        trip = self.trip()
        command = self.pending("return_vehicle", {"trip_id": trip["id"], "hub_id": "H2"})
        self.assertNotEqual(self.row("trips", trip["id"])["status"], "CLOSED")
        self.acknowledge(command)
        self.service = Service(self.db, simulator=True, clock=self.clock)
        self.assertEqual(self.row("trips", trip["id"])["status"], "CLOSED")
        vehicle = self.row("vehicles", "V1")
        self.assertEqual(vehicle["hub_id"], "H2")
        self.assertEqual(self.row("spots", vehicle["spot_id"])["state"], "OCCUPIED")

    def test_stale_resource_cannot_be_allocated(self):
        self.clock.advance(91)
        self.service.tick()
        with self.assertRaises(DomainError):
            self.command("reserve_vehicle", {"vehicle_id": "V1"})
        self.assertFalse(self.row("vehicles", "V1")["available"])

    def test_faulted_vehicle_cannot_be_allocated(self):
        self.command("sim_observe", {"resource_type": "vehicles", "resource_id": "V1",
                                     "health": "OUT_OF_SERVICE"}, OP)
        with self.assertRaises(DomainError):
            self.command("reserve_vehicle", {"vehicle_id": "V1"})

    def test_old_observation_cannot_overwrite_newer_fault(self):
        self.command("sim_observe", {"resource_type": "vehicles", "resource_id": "V1",
                                     "health": "OUT_OF_SERVICE", "sequence": 20,
                                     "observed_at": self.clock()}, OP)
        try:
            self.command("sim_observe", {"resource_type": "vehicles", "resource_id": "V1",
                                         "health": "OPERABLE", "sequence": 19,
                                         "observed_at": self.clock() - 1}, OP)
        except DomainError:
            pass
        self.assertEqual(self.row("vehicles", "V1")["health"], "OUT_OF_SERVICE")

    def test_failed_charge_bundle_has_no_half_parking_commit(self):
        before = self.state()
        with self.assertRaises(DomainError):
            self.parking(charging=True, target_soc=101)
        self.assertEqual(self.rows("rights"), before["rights"])
        self.assertEqual(self.rows("sessions"), before["sessions"])

    def test_faulted_ports_make_bundle_fail_without_silent_parking_fallback(self):
        for port in self.rows("ports"):
            if port["hub_id"] == "H2":
                self.command("sim_observe", {"resource_type": "ports", "resource_id": port["id"],
                                             "health": "OUT_OF_SERVICE"}, OP)
        before = self.state()
        with self.assertRaises(DomainError):
            self.parking(charging=True)
        self.assertEqual(self.rows("rights"), before["rights"])
        self.assertEqual(self.rows("sessions"), before["sessions"])

    def test_charge_bundle_cancel_releases_only_unused_commitments(self):
        right = self.parking(charging=True)
        session = next(s for s in self.rows("sessions") if s["right_id"] == right["id"])
        self.command("cancel_parking", {"right_id": right["id"]})
        self.assertEqual(self.row("rights", right["id"])["status"], "CANCELLED")
        self.assertEqual(self.row("sessions", session["id"])["status"], "CANCELLED")

    def test_cancel_added_charging_preserves_independent_parking_right(self):
        right = self.parking(spot_id="H2-S1")
        session = self.create("sessions", "register_charge", {
            "right_id": right["id"], "target_soc": 60,
        })
        self.command("cancel_charge", {"session_id": session["id"]})
        self.assertEqual(self.row("sessions", session["id"])["status"], "CANCELLED")
        self.assertEqual(self.row("rights", right["id"])["status"], "CONFIRMED")

    def test_cancel_charge_after_parking_keeps_physical_occupancy(self):
        right = self.parking(charging=True)
        session = next(s for s in self.rows("sessions") if s["right_id"] == right["id"])
        self.acknowledge(self.pending("arrive", {"right_id": right["id"]}))
        self.command("cancel_charge", {"session_id": session["id"]})
        self.assertEqual(self.row("sessions", session["id"])["status"], "CANCELLED")
        self.assertEqual(self.row("rights", right["id"])["status"], "CONSUMED")
        self.assertEqual(self.row("spots", right["spot_id"])["state"], "OCCUPIED")

    def test_parking_overlap_on_same_vehicle_is_rejected_even_other_hub(self):
        self.parking()
        with self.assertRaises(DomainError):
            self.parking(hub_id="H3")
        self.assertEqual(len(self.rows("rights")), 1)

    def fill_ordinary_capacity(self, hub_id="H2"):
        hub = self.row("hubs", hub_id)
        slots = int(hub["capacity"] * 0.9) - hub["occupied"] - hub["unknown"] - hub["held"]
        personal = self.row("vehicles", "P1")
        for index in range(slots):
            vehicle = self.create("vehicles", "register_vehicle", {
                "label": f"Capacity test {index}", "battery_kwh": 2,
                "connector": personal["connector"], "soc": 50,
            })
            self.parking(vehicle=vehicle["id"], hub_id=hub_id)
        return self.row("hubs", hub_id)

    def test_ordinary_capacity_cannot_consume_operator_reserve(self):
        hub = self.fill_ordinary_capacity()
        self.assertEqual(hub["occupied"] + hub["unknown"] + hub["held"],
                         int(hub["capacity"] * 0.9))
        with self.assertRaises(DomainError):
            self.parking()

    def test_full_hub_return_keeps_trip_open_and_creates_support(self):
        trip = self.trip()
        self.fill_ordinary_capacity()
        self.command("return_vehicle", {"trip_id": trip["id"], "hub_id": "H2"})
        self.assertEqual(self.row("trips", trip["id"])["status"], "ASSISTANCE_PENDING")
        self.assertTrue(any(i["record_id"] == trip["id"] for i in self.rows("incidents")))
        self.assertIsNone(self.row("vehicles", "V1").get("spot_id"))

    def test_parking_limits_reject_too_short_too_long_and_too_far(self):
        for extra in ({"end": self.clock() + 899},
                      {"end": self.clock() + 12 * 3600 + 1},
                      {"start": self.clock() + 86401, "end": self.clock() + 90001}):
            with self.subTest(extra=extra), self.assertRaises(DomainError):
                self.parking(**extra)
        self.assertEqual(len(self.rows("rights")), 0)

    def test_nonfinite_or_boolean_times_cannot_bypass_booking_constraints(self):
        for value in (float("nan"), float("inf"), float("-inf"), True):
            with self.subTest(value=value), self.assertRaises(DomainError):
                self.parking(start=value)
        self.assertEqual(len(self.rows("rights")), 0)

    def test_used_parking_does_not_expire_or_cancel_into_empty_bay(self):
        right = self.parking()
        self.acknowledge(self.pending("arrive", {"right_id": right["id"]}))
        self.clock.advance(4000)
        self.service.tick()
        self.assertEqual(self.row("spots", right["spot_id"])["state"], "OCCUPIED")
        self.assertEqual(self.row("rights", right["id"])["status"], "CONSUMED")
        with self.assertRaises(DomainError):
            self.command("cancel_parking", {"right_id": right["id"]})

    def test_charging_completion_does_not_unplug_or_free_parking(self):
        right, session = self.charge_ready()
        start = self.pending("start_charge", {"session_id": session["id"]})
        self.assertEqual(self.row("sessions", session["id"])["status"], "START_PENDING")
        self.acknowledge(start)
        self.assertEqual(self.row("sessions", session["id"])["status"], "CHARGING")
        stop = self.pending("stop_charge", {"session_id": session["id"]})
        self.assertEqual(self.row("sessions", session["id"])["status"], "STOP_PENDING")
        self.acknowledge(stop)
        self.assertEqual(self.row("sessions", session["id"])["status"], "COMPLETED")
        port = self.row("ports", session["port_id"])
        self.assertEqual(port["plug"], "CONNECTED")
        self.assertEqual(port["power"], "OFF")
        self.assertEqual(self.row("spots", right["spot_id"])["state"], "OCCUPIED")
        visit = next(v for v in self.rows("visits") if v["right_id"] == right["id"])
        with self.assertRaises(DomainError):
            self.command("depart", {"visit_id": visit["id"]})
        self.acknowledge(self.pending("unplug", {"session_id": session["id"]}))
        self.acknowledge(self.pending("depart", {"visit_id": visit["id"]}))
        self.assertEqual(self.row("spots", right["spot_id"])["state"], "EMPTY")

    def test_start_charge_without_arrival_and_plug_is_rejected(self):
        right = self.parking(charging=True)
        session = next(s for s in self.rows("sessions") if s["right_id"] == right["id"])
        with self.assertRaises(DomainError):
            self.command("start_charge", {"session_id": session["id"]})
        self.assertEqual(self.row("sessions", session["id"])["status"], "BOOKED")

    def test_late_start_ack_cannot_restart_session_after_verified_stop(self):
        _, session = self.charge_ready()
        start = self.pending("start_charge", {"session_id": session["id"]})
        stop = self.pending("stop_charge", {"session_id": session["id"]})
        self.acknowledge(stop)
        try:
            self.acknowledge(start)
        except DomainError:
            pass
        self.assertEqual(self.row("sessions", session["id"])["status"], "COMPLETED")
        self.assertEqual(self.row("ports", session["port_id"])["power"], "OFF")

    def test_expired_unused_bundle_releases_both_halves(self):
        right = self.parking(charging=True)
        session = next(s for s in self.rows("sessions") if s["right_id"] == right["id"])
        self.clock.advance(601)
        self.service.tick()
        self.assertEqual(self.row("rights", right["id"])["status"], "EXPIRED")
        self.assertIn(self.row("sessions", session["id"])["status"], ["EXPIRED", "CANCELLED"])

    def test_schedule_draft_is_not_physical_execution_and_requires_operator(self):
        self.parking(charging=True)
        with self.assertRaises(DomainError):
            self.command("schedule_preview")
        before = self.rows("ports")
        plan = self.create("plans", "schedule_preview", actor=OP)
        self.assertEqual(plan["status"], "DRAFT")
        self.assertEqual(self.rows("ports"), before)
        with self.assertRaises(DomainError):
            self.command("schedule_confirm", {"plan_id": plan["id"]})
        self.command("schedule_confirm", {"plan_id": plan["id"]}, OP)
        self.assertEqual(self.rows("ports"), before)
        self.assertEqual(self.rows("sessions")[0]["status"], "BOOKED")

    def test_schedule_approval_rechecks_fault_after_draft(self):
        right = self.parking(charging=True)
        session = next(s for s in self.rows("sessions") if s["right_id"] == right["id"])
        plan = self.create("plans", "schedule_preview", actor=OP)
        self.command("sim_observe", {"resource_type": "ports", "resource_id": session["port_id"],
                                     "health": "OUT_OF_SERVICE"}, OP)
        with self.assertRaises(DomainError):
            self.command("schedule_confirm", {"plan_id": plan["id"]}, OP)
        self.assertEqual(self.row("ports", session["port_id"])["power"], "OFF")

    def test_support_record_is_owned_and_does_not_close_journey(self):
        trip = self.trip()
        with self.assertRaises(DomainError):
            self.command("support", {"record_id": trip["id"], "message": "Forged report"}, BOB)
        self.command("support", {"record_id": trip["id"], "message": "Cannot reach destination"})
        self.assertNotEqual(self.row("trips", trip["id"])["status"], "CLOSED")
        self.assertTrue(any(i["record_id"] == trip["id"] for i in self.rows("incidents")))

    def test_pending_arrival_claim_outlives_original_window(self):
        right = self.parking(spot_id='H2-S4', end=self.clock() + 900)
        self.pending('arrive', {'right_id': right['id']})
        self.clock.advance(2000)
        self.command('sim_refresh', actor=OP)
        with self.assertRaises(DomainError):
            self.parking(BOB, 'P2', spot_id='H2-S4')
        self.assertEqual(self.row('rights', right['id'])['status'], 'HANDOVER_PENDING')

    def test_departed_parking_right_cannot_back_a_new_session(self):
        right = self.parking(spot_id='H2-S1')
        self.acknowledge(self.pending('arrive', {'right_id': right['id']}))
        visit = next(v for v in self.rows('visits') if v['right_id'] == right['id'])
        self.acknowledge(self.pending('depart', {'visit_id': visit['id']}))
        with self.assertRaises(DomainError):
            self.command('register_charge', {'right_id': right['id'], 'target_soc': 60})

    def test_isolated_origin_blocks_pending_pickup_evidence(self):
        hold = self.hold()
        command = self.pending('pickup', {'hold_id': hold['id']})
        self.command('sim_observe', {'resource_type': 'spots', 'resource_id': 'H1-S3',
                                     'health': 'OUT_OF_SERVICE'}, OP)
        self.assertEqual(self.acknowledge(command)['record']['status'], 'ANOMALY')
        self.assertFalse(self.rows('trips'))
        self.assertEqual(self.row('holds', hold['id'])['status'], 'HANDOVER_PENDING')

    def test_seeded_fleet_charge_claim_blocks_rental_until_release(self):
        session = self.create('sessions', 'fleet_charge', {'vehicle_id': 'V3', 'target_soc': 90}, OP)
        with self.assertRaises(DomainError):
            self.command('reserve_vehicle', {'vehicle_id': 'V3'})
        self.command('cancel_charge', {'session_id': session['id']}, OP)
        self.hold(vehicle='V3')

    def test_disabled_charger_removes_empty_bay_from_available_capacity(self):
        before = self.row('hubs', 'H2')['available']
        self.command('d_resource_state', {'resource_id': 'H2-C1', 'active': False}, OP)
        self.assertEqual(self.row('hubs', 'H2')['available'], before - 1)

    def test_charging_cannot_start_during_pending_unplug(self):
        _, session = self.charge_ready()
        cmd = self.pending('unplug', {'session_id': session['id']})
        with self.assertRaises(DomainError) as ex:
            self.command('start_charge', {'session_id': session['id']})
        self.assertEqual(ex.exception.code, 'UNPLUG_PENDING')
        self.acknowledge(cmd)
        self.assertEqual(self.row('ports', session['port_id'])['plug'], 'UNPLUGGED')

    def test_isolating_vehicle_blocks_power_on(self):
        _, session = self.charge_ready()
        self.command('sim_observe', {'resource_type': 'vehicles', 'resource_id': 'P1',
                                     'health': 'OUT_OF_SERVICE'}, OP)
        with self.assertRaises(DomainError):
            self.command('start_charge', {'session_id': session['id']})
        self.assertEqual(self.row('ports', session['port_id'])['power'], 'OFF')

    def test_field_staff_cannot_read_or_change_student_journeys(self):
        hold = self.hold()
        for role in ('dispatcher', 'technician'):
            actor = dict(id=role, role=role)
            self.assertFalse(self.rows('holds', actor))
            with self.assertRaises(DomainError) as exc:
                self.command('pickup', {'hold_id': hold['id']}, actor)
            self.assertEqual(exc.exception.status, 403)


if __name__ == "__main__":
    unittest.main()
