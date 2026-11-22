"""Reservation credentials do not constitute physical arrival evidence."""
import concurrent.futures
import copy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

from emobility.domain import DomainError, Service

ALICE = {'id': 'alice', 'role': 'student'}
BOB = {'id': 'bob', 'role': 'student'}
OP = {'id': 'operator', 'role': 'operator'}


class ParkingQrTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'qr.sqlite'
        self.now = 1_800_000_000.0
        self.service = Service(self.path, simulator=True, clock=lambda: self.now)

    def command(self, action, payload=None, actor=ALICE, intent=None, service=None):
        return (service or self.service).command(actor, action, payload or {}, intent or uuid.uuid4().hex)

    def booking(self, **changes):
        return dict(vehicle_id='P1', hub_id='H2', start=self.now, end=self.now + 3600, **changes)

    def reserve(self, **changes):
        return self.command('reserve_parking', self.booking(**changes))['record']

    def rows(self, kind):
        return {r['id']: r for r in self.service.snapshot(OP)[kind]}

    def arrival(self, right, **options):
        return self.command('arrive', dict(right_id=right['id'], qr_token=right['qr']['token']), **options)

    def ack(self, kind, outcome='ACK'):
        pending = next(c for c in self.rows('commands').values() if c['kind'] == kind and c['status'] == 'PENDING')
        return self.command('simulate', dict(command_id=pending['id'], outcome=outcome, event_id=uuid.uuid4().hex), OP)

    def rejects(self, code, action, payload, actor=ALICE):
        with self.assertRaises(DomainError) as error:
            self.command(action, payload, actor)
        self.assertEqual(error.exception.code, code)

    def test_success_unique_opaque_code_and_stable_snapshot_restart_receipt(self):
        payload = self.booking()
        first = self.command('reserve_parking', payload, intent='qr-reservation-retry')
        right = first['record']; qr = right['qr']
        self.assertRegex(qr['token'], r'^emobility:parking:[A-Za-z0-9_-]{43}$')
        self.assertNotIn('alice', qr['token'])
        self.assertNotIn(right['id'], qr['token'])
        self.assertEqual(qr['issued_at'], self.now)
        self.assertEqual(qr['expires_at'], self.now + 600)
        self.assertEqual(self.rows('rights')[right['id']]['qr'], qr)
        self.service = Service(self.path, simulator=True, clock=lambda: self.now)
        self.assertEqual(self.command('reserve_parking', payload, intent='qr-reservation-retry'), first)
        self.assertEqual(self.service.parking_qr(ALICE, right['id'])['token'], qr['token'])
        bob = self.command('reserve_parking', dict(payload, vehicle_id='P2'), BOB)['record']
        self.assertNotEqual(qr['token'], bob['qr']['token'])
        self.assertEqual(len(self.rows('rights')), 2)

    def test_failed_bundle_rolls_back_right_and_qr(self):
        self.rejects('INVALID_TARGET', 'reserve_parking', self.booking(charging=True, target_soc=20))
        self.assertEqual(self.rows('rights'), {})
        self.assertEqual(self.rows('sessions'), {})

    def test_code_survives_loading_database_in_a_new_python_process(self):
        right = self.reserve()
        script = ('import sys; from emobility.domain import Service; '
                  'service=Service(sys.argv[1], simulator=True, clock=lambda:float(sys.argv[3])); '
                  "print(service.parking_qr({'id':'alice','role':'student'},sys.argv[2])['token'])")
        token = subprocess.check_output(
            [sys.executable, '-c', script, str(self.path), right['id'], str(self.now)],
            cwd=Path(__file__).resolve().parents[1], text=True, timeout=15).strip()
        self.assertEqual(token, right['qr']['token'])

    def test_cannot_use_id_without_code_or_wrong_code(self):
        right = self.reserve()
        for invalid in (None, '', right['id'], 'emobility:parking:guess', ['x'], '\u00e9'):
            with self.subTest(code=invalid):
                self.rejects('INVALID_QR', 'arrive', dict(right_id=right['id'], qr_token=invalid))
        self.rejects('INVALID_QR', 'arrive', dict(right_id=right['id']))
        self.assertEqual(self.rows('commands'), {})
        self.assertEqual(self.rows('spots')[right['spot_id']]['state'], 'EMPTY')

    def test_owner_is_required_for_code_and_qr_view(self):
        right = self.reserve()
        self.rejects('FORBIDDEN', 'arrive', dict(qr_token=right['qr']['token']), BOB)
        with self.assertRaises(DomainError) as error:
            self.service.parking_qr(BOB, right['id'])
        self.assertEqual(error.exception.code, 'FORBIDDEN')
        self.assertEqual(self.service.snapshot(BOB)['rights'], [])
        with self.assertRaises(DomainError):
            self.service.parking_qr({'id': 'alice', 'role': 'operator'}, right['id'])

    def test_qr_is_bound_to_specific_right(self):
        first = self.reserve()
        self.command('cancel_parking', dict(right_id=first['id']))
        second = self.reserve()
        self.rejects('INVALID_QR', 'arrive', dict(right_id=second['id'], qr_token=first['qr']['token']))

    def test_code_only_request_then_ack_then_reuse_is_rejected(self):
        right = self.reserve()
        reply = self.command('arrive', dict(qr_token=right['qr']['token']), intent='qr-checkin-first')
        self.assertEqual(reply['status'], 'PENDING_VERIFICATION')
        self.assertEqual(self.rows('spots')[right['spot_id']]['state'], 'EMPTY')
        self.assertFalse(any(v['right_id'] == right['id'] for v in self.rows('visits').values()))
        self.assertEqual(self.service.parking_qr(ALICE, right['id'])['status'], 'HANDOVER_PENDING')
        self.assertFalse(self.service.parking_qr(ALICE, right['id'])['usable'])
        self.arrival(right)  # New intent while pending must not create a second command.
        self.assertEqual(len(self.rows('commands')), 1)
        self.ack('ARRIVAL')
        self.assertEqual(self.rows('spots')[right['spot_id']]['state'], 'OCCUPIED')
        self.assertEqual(self.rows('vehicles')['P1']['spot_id'], right['spot_id'])
        visits = [v for v in self.rows('visits').values() if v['right_id'] == right['id']]
        self.assertEqual(len(visits), 1)
        self.assertEqual(visits[0]['status'], 'PARKED')
        self.rejects('INVALID_RIGHT', 'arrive', dict(qr_token=right['qr']['token']))
        self.assertEqual(self.command('arrive', dict(qr_token=right['qr']['token']), intent='qr-checkin-first'), reply)
        self.assertEqual(len([v for v in self.rows('visits').values() if v['right_id'] == right['id']]), 1)
        self.assertFalse(self.service.parking_qr(ALICE, right['id'])['usable'])

    def test_cancelled_and_expired_codes_rejected(self):
        right = self.reserve()
        self.command('cancel_parking', dict(right_id=right['id']))
        self.rejects('INVALID_RIGHT', 'arrive', dict(qr_token=right['qr']['token']))
        self.assertEqual(self.service.parking_qr(ALICE, right['id'])['status'], 'CANCELLED')
        right = self.reserve()
        self.now += 601
        self.command('sim_refresh', actor=OP)
        self.rejects('INVALID_RIGHT', 'arrive', dict(qr_token=right['qr']['token']))
        qr = self.service.parking_qr(ALICE, right['id'])
        self.assertEqual(qr['status'], 'EXPIRED')
        self.assertFalse(qr['usable'])
        self.assertEqual(self.rows('commands'), {})

    def test_grace_boundary_and_pending_claim_survive_timeout(self):
        right = self.reserve()
        self.now += 600
        self.command('sim_refresh', actor=OP)
        self.assertTrue(self.service.parking_qr(ALICE, right['id'])['usable'])
        self.arrival(right)
        self.now += 3601
        self.arrival(right)
        self.assertEqual(len(self.rows('commands')), 1)
        self.ack('ARRIVAL')
        self.assertEqual(self.rows('rights')[right['id']]['status'], 'CONSUMED')

    def test_rejected_reception_can_retry_same_code_with_new_intent(self):
        right = self.reserve()
        self.arrival(right); self.ack('ARRIVAL', 'REJECT')
        self.assertTrue(self.service.parking_qr(ALICE, right['id'])['usable'])
        self.arrival(right); self.ack('ARRIVAL')
        self.assertEqual(len([v for v in self.rows('visits').values() if v['right_id'] == right['id']]), 1)

    def test_existing_reception_rules_still_apply(self):
        right = self.reserve()
        self.command('sim_observe', dict(resource_type='spots', resource_id=right['spot_id'], health='OUT_OF_SERVICE'), OP)
        self.rejects('RECEPTION_BLOCKED', 'arrive', dict(qr_token=right['qr']['token']))
        self.assertEqual(self.rows('commands'), {})

    def test_concurrent_reservation_replay_issues_one_code(self):
        payload = self.booking()
        def request(_):
            service = Service(self.path, simulator=True, clock=lambda: self.now)
            return self.command('reserve_parking', payload, intent='parallel-qr-reservation', service=service)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(request, range(2)))
        self.assertEqual(replies[0], replies[1])
        self.assertEqual(len(self.rows('rights')), 1)

    def test_concurrent_scans_create_one_arrival_and_cancel_race_is_safe(self):
        right = self.reserve()
        def scan(_):
            service = Service(self.path, simulator=True, clock=lambda: self.now)
            return self.arrival(right, service=service)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(scan, range(2)))
        self.assertEqual(len(self.rows('commands')), 1)
        self.rejects('PARKING_IN_USE', 'cancel_parking', dict(right_id=right['id']))
        self.ack('ARRIVAL')
        self.assertEqual(len([v for v in self.rows('visits').values() if v['right_id'] == right['id']]), 1)

    def test_legacy_database_additive_migration_is_stable(self):
        right = self.reserve()
        # Manufacture a pre-QR DB only in this isolated fixture.
        with self.service.connect() as db:
            legacy = self.service.load(db)
            legacy['rights'][right['id']].pop('qr')
            self.service.save(db, legacy)
            before_receipts = db.execute('SELECT * FROM receipts').fetchall()
        expected = copy.deepcopy(legacy)
        self.service = Service(self.path, simulator=True, clock=lambda: self.now)
        code = self.service.parking_qr(ALICE, right['id'])['token']
        with self.service.connect() as db:
            upgraded = self.service.load(db)
            self.assertEqual(db.execute('SELECT * FROM receipts').fetchall(), before_receipts)
        upgraded['rights'][right['id']].pop('qr')
        self.assertEqual(upgraded, expected)
        self.service = Service(self.path, simulator=True, clock=lambda: self.now)
        self.assertEqual(self.service.parking_qr(ALICE, right['id'])['token'], code)
        self.command('arrive', dict(qr_token=code))

    def test_viewing_qr_does_not_write_revisions_or_device_commands(self):
        right = self.reserve()
        first = self.service.snapshot(ALICE)
        a = self.service.parking_qr(ALICE, right['id'])
        b = self.service.parking_qr(ALICE, right['id'])
        self.assertEqual(a, b)
        self.assertIn('<svg', a['svg'])
        self.assertEqual(first, self.service.snapshot(ALICE))


if __name__ == '__main__':
    unittest.main()
