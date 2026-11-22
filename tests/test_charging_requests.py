"""Charging-only approval, real QR credentials and unchanged physical boundary."""
import concurrent.futures
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from emobility.domain import DomainError, Service

ALICE = dict(id='alice', role='student')
BOB = dict(id='bob', role='student')
OP = dict(id='operator', role='operator')


class ChargingRequestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 1800000000.0
        self.path = Path(self.temp.name) / 'charge.sqlite'
        self.service = Service(self.path, simulator=True, clock=lambda: self.now)

    def cmd(self, action, payload=None, actor=ALICE, intent=None):
        return self.service.command(actor, action, payload or {}, intent or uuid4().hex)['record']

    def rows(self, kind):
        return self.service.snapshot(OP)[kind]

    def submit(self, actor=ALICE, **changes):
        data = dict(vehicle_id='P1' if actor == ALICE else 'P2', hub_id='H1',
                    declared_soc=30, target_soc=90, arrival_time=self.now)
        data.update(changes)
        return self.cmd('submit_charge_request', data, actor)

    def approve(self, request):
        return self.cmd('approve_charge_request', dict(request_id=request['id']), OP)

    def rejects(self, code, action, payload, actor=ALICE):
        with self.assertRaises(DomainError) as caught:
            self.cmd(action, payload, actor)
        self.assertEqual(caught.exception.code, code)

    def mutate(self, kind, rid, **changes):
        with self.service.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self.service.load(db)
            state[kind][rid].update(changes)
            self.service.save(db, state)

    def ack(self, kind):
        command = next(c for c in self.rows('commands') if c['kind'] == kind and c['status'] == 'PENDING')
        self.cmd('simulate', dict(command_id=command['id']), OP)

    def test_tc01_02_08_12_13_23_pending_approval_linkage_and_duplicate(self):
        request = self.submit(declared_soc=10)
        self.assertEqual(request['status'], 'PENDING')
        self.assertTrue(request['proposal']['available'])
        self.assertEqual(self.rows('rights'), [])
        self.assertEqual(self.rows('sessions'), [])
        with self.assertRaises(DomainError):
            self.service.charging_qr(ALICE, request['id'])
        booked = self.approve(request)
        self.assertEqual(booked['status'], 'BOOKED')
        self.assertEqual(self.approve(request), booked)
        self.assertEqual(len(self.rows('rights')), 1)
        session = self.rows('sessions')[0]
        right = self.rows('rights')[0]
        self.assertEqual(session['right_id'], right['id'])
        self.assertEqual(session['charge_request_id'], request['id'])
        self.assertEqual(right['reservation_type'], 'CHARGING_ONLY')
        self.assertAlmostEqual(session['duration'], 1.6 / (3.7 * .9) * 3600)
        self.assertEqual(next(v for v in self.rows('vehicles') if v['id']=='P1')['soc'], 30)
        qr = self.service.charging_qr(ALICE, request['id'])
        self.assertIn('<svg', qr['svg'])
        self.assertTrue(qr['usable'])
        restarted = Service(self.path, simulator=True, clock=lambda: self.now)
        self.assertEqual(restarted.charging_qr(ALICE, request['id'])['token'], qr['token'])

    def test_tc03_rejection_and_pending_cancellation_hold_nothing(self):
        request = self.submit()
        rejected = self.cmd('reject_charge_request', dict(request_id=request['id'], reason='Port maintenance'), OP)
        self.assertEqual(rejected['status'], 'REJECTED')
        self.assertEqual(rejected['rejection_reason'], 'Port maintenance')
        request = self.submit()
        self.cmd('cancel_charge_request', dict(request_id=request['id']))
        self.assertEqual(self.rows('rights'), [])
        self.assertEqual(self.rows('sessions'), [])

    def test_tc04_validation_and_unapproved_inputs(self):
        for changes in ({'declared_soc':90}, {'declared_soc':-1}, {'target_soc':101},
                        {'arrival_time':self.now+86401}, {'arrival_time':self.now-61}):
            with self.subTest(changes=changes), self.assertRaises(DomainError):
                self.submit(**changes)
        self.rejects('FORBIDDEN', 'submit_charge_request', dict(vehicle_id='P2'), ALICE)
        self.assertEqual(self.rows('charge_requests'), [])

    def test_tc05_06_09_failures_rollback_and_revalidate(self):
        for kind, rid, change in [('ports','H1-C2',dict(connector='OTHER')),
                                   ('hubs','H1',dict(power_kw=0)),
                                   ('ports','H1-C2',dict(health='OUT_OF_SERVICE'))]:
            with self.subTest(change=change):
                request = self.submit()
                self.mutate(kind, rid, **change)
                with self.assertRaises(DomainError):
                    self.approve(request)
                self.assertEqual(self.rows('rights'), [])
                self.assertEqual(self.rows('sessions'), [])
                self.assertEqual(self.rows('charge_requests')[-1]['status'], 'PENDING')
                self.cmd('cancel_charge_request', dict(request_id=request['id']))
                self.mutate('ports','H1-C2',connector='TYPE2',health='OPERABLE')
                self.mutate('hubs','H1',power_kw=7.4)

    def test_tc07_racing_approvals_never_double_book(self):
        requests = [self.submit(), self.submit(BOB)]
        def attempt(request):
            try:
                return self.approve(request)['status']
            except DomainError:
                return 'FAILED'
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(attempt, requests))
        self.assertCountEqual(results, ['BOOKED', 'FAILED'])
        self.assertEqual(len(self.rows('rights')), 1)
        self.assertEqual(len(self.rows('sessions')), 1)

    def test_hub_power_competition_across_different_ports(self):
        self.mutate('hubs','H2',power_kw=3.7)
        first = self.approve(self.submit(hub_id='H2'))
        second = self.submit(BOB,hub_id='H2')
        self.rejects('POWER_CONFLICT','approve_charge_request',dict(request_id=second['id']),OP)
        self.assertEqual(len(self.rows('sessions')),1)
        self.assertEqual(first['kw'],3.7)

    def test_failure_after_parking_allocation_rolls_back_everything(self):
        request = self.submit()
        with patch.object(self.service,'create_charge',side_effect=DomainError('TEST_FAILURE','Charging allocation failed')):
            self.rejects('TEST_FAILURE','approve_charge_request',dict(request_id=request['id']),OP)
        self.assertEqual(self.rows('rights'),[])
        self.assertEqual(self.rows('sessions'),[])
        self.assertNotIn('qr',self.rows('charge_requests')[0])

    def test_tc10_14_cancellation_and_expiry_revoke_codes(self):
        booked = self.approve(self.submit())
        payload = dict(request_id=booked['id'], qr_token=booked['qr']['token'])
        self.cmd('cancel_charge_request', dict(request_id=booked['id']))
        self.rejects('INVALID_STATE', 'scan_charge', payload)
        self.assertEqual(self.rows('rights')[0]['status'], 'CANCELLED')
        self.assertEqual(self.rows('sessions')[0]['status'], 'CANCELLED')
        booked = self.approve(self.submit())
        self.now += 601
        self.assertFalse(self.service.charging_qr(ALICE, booked['id'])['usable'])
        self.rejects('INVALID_STATE', 'scan_charge', dict(request_id=booked['id'], qr_token=booked['qr']['token']))

    def test_tc15_16_access_control_and_scan_duplicate_is_not_physical_arrival(self):
        request = self.submit()
        self.rejects('FORBIDDEN', 'approve_charge_request', dict(request_id=request['id']))
        self.rejects('FORBIDDEN', 'reject_charge_request', dict(request_id=request['id'], reason='no'), BOB)
        booked = self.approve(request)
        payload = dict(request_id=booked['id'], qr_token=booked['qr']['token'])
        self.rejects('FORBIDDEN', 'scan_charge', payload, BOB)
        with self.assertRaises(DomainError):
            self.service.charging_qr(BOB, booked['id'])
        self.assertEqual(self.service.snapshot(BOB)['charge_requests'], [])
        self.rejects('INVALID_QR', 'scan_charge', dict(payload, qr_token='wrong'))
        self.cmd('scan_charge', payload)
        self.cmd('scan_charge', payload)
        self.assertEqual(len(self.rows('commands')), 1)
        self.assertEqual(next(s for s in self.rows('spots') if s['id']==booked['spot_id'])['state'], 'EMPTY')
        self.assertEqual(self.rows('sessions')[0]['status'], 'BOOKED')

    def test_tc17_completion_requires_unplug_and_departure_evidence(self):
        booked = self.approve(self.submit())
        self.cmd('scan_charge', dict(request_id=booked['id'], qr_token=booked['qr']['token']))
        self.ack('ARRIVAL')
        self.rejects('PARKING_IN_USE', 'cancel_charge_request', dict(request_id=booked['id']))
        payload = dict(session_id=booked['session_id'])
        self.cmd('plug', payload); self.ack('PLUG')
        self.cmd('start_charge', payload); self.ack('START')
        self.cmd('stop_charge', payload); self.ack('STOP')
        self.assertEqual(self.rows('sessions')[0]['status'], 'COMPLETED')
        spot = lambda: next(s for s in self.rows('spots') if s['id']==booked['spot_id'])
        self.assertEqual(spot()['state'], 'OCCUPIED')
        visit = next(v for v in self.rows('visits') if v.get('right_id')==booked['right_id'])
        self.rejects('CONNECTED', 'depart', dict(visit_id=visit['id']))
        self.cmd('unplug', payload); self.ack('UNPLUG')
        self.cmd('depart', dict(visit_id=visit['id']))
        self.assertEqual(spot()['state'], 'OCCUPIED')
        self.ack('DEPARTURE')
        self.assertEqual(spot()['state'], 'EMPTY')

    def test_tc11_18_19_20_existing_booking_modes(self):
        booking = dict(vehicle_id='P1',hub_id='H2',start=self.now,end=self.now+3600,spot_id='H2-S1')
        right = self.cmd('reserve_parking', booking)
        self.assertEqual(self.rows('sessions'), [])
        session = self.cmd('register_charge', dict(right_id=right['id'],target_soc=80))
        self.assertEqual(session['reservation_type'], 'ADD_CHARGING')
        self.cmd('cancel_charge', dict(session_id=session['id']))
        self.assertEqual(self.rows('rights')[0]['status'], 'CONFIRMED')
        self.cmd('cancel_parking',dict(right_id=right['id']))
        right = self.cmd('reserve_parking',dict(booking,charging=True,target_soc=80))
        self.assertEqual(right['reservation_type'], 'PARKING_AND_CHARGING')
        self.assertEqual(sum(s['status']=='BOOKED' for s in self.rows('sessions')),1)

    def test_arrival_scope_and_submission_receipt(self):
        payload = dict(vehicle_id='P1',hub_id='H1',declared_soc=20,target_soc=80,arrival_time=self.now+3600)
        first = self.cmd('submit_charge_request',payload,intent='stable-submit')
        self.assertEqual(self.cmd('submit_charge_request',payload,intent='stable-submit'),first)
        booked = self.approve(first)
        self.assertEqual(booked['scheduled_start'],payload['arrival_time'])
        self.rejects('OUTSIDE_SCHEDULE','scan_charge',dict(request_id=booked['id'],qr_token=booked['qr']['token']))


if __name__ == '__main__':
    unittest.main()
