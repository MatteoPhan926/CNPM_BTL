"""Isolated lifecycle checks of the backend dashboard projection."""
import copy
from pathlib import Path
import tempfile
import unittest
import uuid

from emobility.active_services import active_service_count
from emobility.domain import Service

ALICE = {'id': 'alice', 'role': 'student'}
BOB = {'id': 'bob', 'role': 'student'}
OP = {'id': 'operator', 'role': 'operator'}


class ActiveServiceCounterTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'isolated.sqlite'
        self.now = 1_800_000_000.0
        self.service = Service(self.path, simulator=True, clock=lambda: self.now)

    def command(self, action, payload=None, actor=ALICE, intent=None):
        result = self.service.command(actor, action, payload or {}, intent or uuid.uuid4().hex)
        return result.get('record', result)

    def rows(self, kind):
        return self.service.snapshot(OP)[kind]

    def count(self, expected, actor=ALICE):
        self.assertEqual(self.service.snapshot(actor)['active_services'], expected)
        with self.service.connect() as db:
            state = self.service.load(db)
        before = copy.deepcopy(state)
        self.assertEqual(active_service_count(state, actor['id']), expected)
        self.assertEqual(state, before, 'Projection must not mutate domain state')

    def reserve(self, **changes):
        payload = dict(vehicle_id='P1', hub_id='H2', start=self.now,
                       end=self.now + 3600, charging=False, target_soc=70)
        payload.update(changes)
        return self.command('reserve_parking', payload)

    def ack(self, kind, outcome='ACK'):
        cmd = next(c for c in self.rows('commands') if c['kind'] == kind and c['status'] == 'PENDING')
        return self.command('simulate', dict(command_id=cmd['id'], outcome=outcome,
                                             event_id=uuid.uuid4().hex), OP)

    def arrive(self, right):
        self.command('arrive', dict(right_id=right['id'], qr_token=right['qr']['token']))
        self.count(1)
        self.ack('ARRIVAL')
        self.count(1)
        return next(v for v in self.rows('visits') if v['right_id'] == right['id'])

    def test_new_user_cancel_and_expiry(self):
        self.count(0); self.count(0, BOB)
        right = self.reserve(); self.count(1)
        self.command('cancel_parking', {'right_id': right['id']}); self.count(0)
        self.reserve(); self.count(1)
        self.now += 601
        self.count(0)

    def test_arrival_departure_and_pending_timeout(self):
        right = self.reserve()
        self.command('arrive', dict(qr_token=right['qr']['token']))
        self.now += 3601
        self.count(1)
        self.ack('ARRIVAL'); self.count(1)
        visit = next(v for v in self.rows('visits') if v['right_id'] == right['id'])
        self.command('depart', {'visit_id': visit['id']}); self.count(1)
        self.ack('DEPARTURE'); self.count(0)

    def test_rental_hold_pickup_return_and_fleet_occupancy(self):
        hold = self.command('reserve_vehicle', {'vehicle_id': 'V1'}); self.count(1)
        self.command('pickup', {'hold_id': hold['id']}); self.count(1)
        self.ack('PICKUP'); self.count(1)
        trip = self.rows('trips')[0]
        self.command('return_vehicle', {'trip_id': trip['id'], 'hub_id': 'H3'}); self.count(1)
        self.ack('RETURN'); self.count(0)
        self.assertTrue(any(v['owner_id'] == 'alice' and v['status'] == 'PARKED' for v in self.rows('visits')))

    def test_hold_cancel_and_expiry(self):
        hold = self.command('reserve_vehicle', {'vehicle_id': 'V1'}); self.count(1)
        self.command('cancel_hold', {'hold_id': hold['id']}); self.count(0)
        self.command('reserve_vehicle', {'vehicle_id': 'V1'})
        self.now += 600
        self.count(0)

    def test_bundle_complete_lifecycle(self):
        right = self.reserve(charging=True); self.count(1)
        visit = self.arrive(right)
        session = self.rows('sessions')[0]
        for action, evidence in [('plug', 'PLUG'), ('start_charge', 'START'),
                                 ('stop_charge', 'STOP'), ('unplug', 'UNPLUG')]:
            self.command(action, {'session_id': session['id']}); self.count(1)
            self.ack(evidence); self.count(1)
        self.command('depart', {'visit_id': visit['id']}); self.count(1)
        self.ack('DEPARTURE'); self.count(0)

    def test_bundle_cancel_expiry_and_no_extra_terminal_count(self):
        right = self.reserve(charging=True); self.count(1)
        session = self.rows('sessions')[0]
        self.command('cancel_charge', {'session_id': session['id']}); self.count(0)
        self.reserve(charging=True); self.count(1)
        self.now += 601
        self.count(0)

    def test_independent_charging_remains_separate(self):
        right = self.reserve(spot_id='H2-S1')
        self.count(1)
        session = self.command('register_charge', {'right_id': right['id'], 'target_soc': 70})
        self.count(2)
        self.command('cancel_charge', {'session_id': session['id']}); self.count(1)
        self.command('cancel_parking', {'right_id': right['id']}); self.count(0)

    def test_user_isolation_refresh_restart_and_receipt_replay(self):
        operator_before = self.service.snapshot(OP)['active_services']
        payload = dict(vehicle_id='P1', hub_id='H2', start=self.now, end=self.now + 3600)
        self.command('reserve_parking', payload, intent='same-booking')
        self.count(1); self.count(0, BOB); self.count(operator_before, OP)
        self.service = Service(self.path, simulator=True, clock=lambda: self.now)
        self.command('reserve_parking', payload, intent='same-booking')
        self.count(1); self.count(0, BOB)
        self.command('reserve_parking', dict(payload, vehicle_id='P2'), BOB)
        self.count(1); self.count(1, BOB)
        self.assertEqual(len(self.rows('rights')), 2)

    def test_recovery_offer_not_counted_before_consent(self):
        right = self.reserve()
        incident = self.command('support', {'record_id': right['id'], 'message': 'Alternative reception please'})
        self.command('capacity_plan', {'incident_id': incident['id'], 'hub_id': 'H3', 'reason': 'Alternative'}, OP)
        self.count(1)
        self.command('accept_capacity', {'incident_id': incident['id'], 'accept': True})
        self.count(1)

    def test_unknown_and_rejected_evidence_do_not_finish_service(self):
        right = self.reserve()
        self.command('arrive', {'qr_token': right['qr']['token']})
        self.ack('ARRIVAL', 'UNKNOWN'); self.count(1)
        self.ack('ARRIVAL', 'REJECT'); self.count(1)
        self.arrive(right)
        self.count(1)


if __name__ == '__main__':
    unittest.main()
