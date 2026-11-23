"""Rental QR credentials are scoped, durable and never physical evidence."""
import concurrent.futures
from pathlib import Path
import tempfile
import unittest
import uuid

from emobility.domain import DomainError, Service

ALICE = {'id': 'alice', 'role': 'student'}
BOB = {'id': 'bob', 'role': 'student'}
OP = {'id': 'operator', 'role': 'operator'}


class RentalQrTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'rental.sqlite'
        self.now = 1_800_000_000.0
        self.service = Service(self.path, simulator=True, clock=lambda: self.now)

    def command(self, action, payload=None, actor=ALICE, intent=None, service=None):
        return (service or self.service).command(actor, action, payload or {}, intent or uuid.uuid4().hex)

    def hold(self):
        return self.command('reserve_vehicle', {'vehicle_id': 'V1'})['record']

    def scan(self, hold, **kwargs):
        return self.command('scan_rental', {'hold_id': hold['id'], 'qr_token': hold['qr']['token']}, **kwargs)

    def rejects(self, code, action, payload, actor=ALICE):
        with self.assertRaises(DomainError) as caught:
            self.command(action, payload, actor)
        self.assertEqual(caught.exception.code, code)

    def test_durable_unique_qr_bound_to_hold_owner_vehicle_hub_expiry(self):
        hold = self.hold()
        qr = self.service.rental_qr(ALICE, hold['id'])
        self.assertRegex(qr['token'], r'^emobility:rental:[A-Za-z0-9_-]{43}$')
        self.assertEqual((qr['hold_id'], qr['owner_id'], qr['vehicle_id'], qr['pickup_hub_id']),
                         (hold['id'], 'alice', 'V1', 'H1'))
        self.assertEqual(qr['expires_at'], hold['expires_at'])
        self.assertIn('<svg', qr['svg'])
        self.service = Service(self.path, simulator=True, clock=lambda: self.now)
        self.assertEqual(self.service.rental_qr(ALICE, hold['id']), qr)
        bob = self.command('reserve_vehicle', {'vehicle_id': 'V2'}, BOB)['record']
        self.assertNotEqual(bob['qr']['token'], qr['token'])

    def test_invalid_foreign_and_mismatched_credentials(self):
        hold = self.hold()
        for value in (None, '', hold['id'], 'emobility:rental:guess', ['token'], '\u00e9'):
            self.rejects('INVALID_QR', 'scan_rental', {'hold_id': hold['id'], 'qr_token': value})
        self.rejects('FORBIDDEN', 'scan_rental', {'qr_token': hold['qr']['token']}, BOB)
        with self.assertRaises(DomainError) as caught:
            self.service.rental_qr(BOB, hold['id'])
        self.assertEqual(caught.exception.code, 'FORBIDDEN')
        self.assertEqual(self.service.snapshot(BOB)['holds'], [])
        self.command('cancel_hold', {'hold_id': hold['id']})
        replacement = self.hold()
        self.rejects('INVALID_QR', 'scan_rental', {'hold_id': replacement['id'], 'qr_token': hold['qr']['token']})

    def test_cancelled_expired_and_exact_expiry_are_unusable(self):
        hold = self.hold()
        self.command('cancel_hold', {'hold_id': hold['id']})
        self.rejects('HOLD_EXPIRED', 'scan_rental', {'qr_token': hold['qr']['token']})
        self.assertFalse(self.service.rental_qr(ALICE, hold['id'])['usable'])
        hold = self.hold()
        self.now = hold['expires_at']
        self.rejects('HOLD_EXPIRED', 'scan_rental', {'qr_token': hold['qr']['token']})
        self.assertFalse(self.service.rental_qr(ALICE, hold['id'])['usable'])
        self.assertEqual(self.service.snapshot(OP)['commands'], [])

    def test_concurrent_scans_only_request_one_handover_and_ack_one_journey(self):
        hold = self.hold()
        def scan(_):
            service = Service(self.path, simulator=True, clock=lambda: self.now)
            return self.scan(hold, service=service)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(scan, range(2)))
        state = self.service.snapshot(OP)
        self.assertEqual(len(state['commands']), 1)
        self.assertEqual(state['trips'], [])
        self.assertEqual(next(s for s in state['spots'] if s['id'] == 'H1-S3')['state'], 'OCCUPIED')
        self.assertFalse(self.service.rental_qr(ALICE, hold['id'])['usable'])
        cmd = state['commands'][0]
        self.command('simulate', {'command_id': cmd['id'], 'outcome': 'ACK'}, OP)
        self.rejects('HOLD_EXPIRED', 'scan_rental', {'qr_token': hold['qr']['token']})
        self.assertEqual(len(self.service.snapshot(OP)['trips']), 1)

    def test_same_intent_replays_and_failed_readiness_creates_no_command(self):
        hold = self.hold()
        self.command('sim_observe', {'resource_type': 'vehicles', 'resource_id': 'V1', 'health': 'OUT_OF_SERVICE'}, OP)
        self.rejects('VEHICLE_UNAVAILABLE', 'scan_rental', {'qr_token': hold['qr']['token']})
        self.assertEqual(self.service.snapshot(OP)['commands'], [])
        self.command('sim_observe', {'resource_type': 'vehicles', 'resource_id': 'V1', 'health': 'OPERABLE'}, OP)
        first = self.scan(hold, intent='scan-retry')
        self.assertEqual(first, self.scan(hold, intent='scan-retry'))

    def test_legacy_active_hold_receives_stable_additive_code(self):
        hold = self.hold()
        with self.service.connect() as db:
            state = self.service.load(db)
            state['holds'][hold['id']].pop('qr')
            state['holds'][hold['id']].pop('pickup_hub_id')
            self.service.save(db, state)
            receipts = db.execute('SELECT * FROM receipts').fetchall()
        self.service = Service(self.path, simulator=True, clock=lambda: self.now)
        qr = self.service.rental_qr(ALICE, hold['id'])
        self.assertEqual(qr['pickup_hub_id'], 'H1')
        self.service = Service(self.path, simulator=True, clock=lambda: self.now)
        self.assertEqual(self.service.rental_qr(ALICE, hold['id']), qr)
        with self.service.connect() as db:
            self.assertEqual(db.execute('SELECT * FROM receipts').fetchall(), receipts)


if __name__ == '__main__':
    unittest.main()
