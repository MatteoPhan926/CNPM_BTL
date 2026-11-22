"""IoT orchestration preserves existing allocation and physical evidence gates."""
import tempfile
from pathlib import Path
import unittest
from uuid import uuid4

from emobility.domain import DomainError, Service

ALICE = dict(id='alice',role='student')
OP = dict(id='operator',role='operator')


class IotWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 1800000000.0
        self.service = Service(Path(self.temp.name)/'iot.sqlite',simulator=True,clock=lambda:self.now)

    def cmd(self, action, payload=None, actor=ALICE):
        return self.service.command(actor,action,payload or {},uuid4().hex)['record']

    def rows(self, collection):
        return self.service.snapshot(OP)[collection]

    def row(self, collection, rid):
        return next(r for r in self.rows(collection) if r['id']==rid)

    def reject(self, code, action, payload, actor=OP):
        with self.assertRaises(DomainError) as caught:
            self.cmd(action,payload,actor)
        self.assertEqual(caught.exception.code,code)

    def parking(self, charging=False, start=None):
        return self.cmd('reserve_parking',dict(vehicle_id='P1',hub_id='H2',spot_id='H2-S1',
            start=self.now if start is None else start,end=self.now+3600,charging=charging,target_soc=80))

    def scan(self, record, collection='rights'):
        spot = record.get('spot_id','H1-S3')
        return self.cmd('sim_iot_scan',dict(qr_token=record['qr']['token'],vehicle_id=record['vehicle_id'],
                        hub_id=record.get('hub_id','H1'),spot_id=spot),OP)

    def ack(self, kind):
        pending = next(c for c in self.rows('commands') if c['kind']==kind and c['status']=='PENDING')
        return self.cmd('simulate',dict(command_id=pending['id']),OP)

    def event(self, kind, record, **changes):
        if 'port_id' in record:
            port = self.row('ports',record['port_id'])
            scope = dict(hub_id=port['hub_id'],spot_id=port['spot_id'],port_id=port['id'])
        else:
            spot = self.row('spots',record['spot_id'])
            scope = dict(hub_id=spot['hub_id'],spot_id=spot['id'])
        payload = dict(kind=kind,record_id=record['id'],vehicle_id=record['vehicle_id'],event_id=uuid4().hex,**scope)
        payload.update(changes)
        return self.cmd('sim_iot_event',payload,OP)

    def test_rental_scan_and_physical_pickup(self):
        hold = self.cmd('reserve_vehicle',dict(vehicle_id='V1'))
        self.scan(hold,'holds'); self.scan(hold,'holds')
        self.assertEqual(self.rows('trips'),[])
        self.assertEqual(len(self.rows('commands')),1)
        self.ack('PICKUP')
        self.assertEqual(self.row('holds',hold['id'])['status'],'CONSUMED')
        self.assertEqual(len(self.rows('trips')),1)

    def test_scan_scope_expiry_and_authorization(self):
        right = self.parking()
        payload = dict(qr_token=right['qr']['token'],vehicle_id='P1',hub_id='H2',spot_id='H2-S1')
        self.reject('FORBIDDEN','sim_iot_scan',payload,ALICE)
        for key,value in [('hub_id','H1'),('spot_id','H2-S2'),('vehicle_id','P2')]:
            self.reject('DEVICE_SCOPE','sim_iot_scan',dict(payload,**{key:value}))
        self.assertEqual(self.rows('commands'),[])
        self.cmd('cancel_parking',dict(right_id=right['id']))
        self.reject('INVALID_RIGHT','sim_iot_scan',payload)
        right = self.parking()
        payload['qr_token'] = right['qr']['token']
        self.now += 601
        self.reject('INVALID_RIGHT','sim_iot_scan',payload)

    def test_simulator_disabled(self):
        self.service.simulator = False
        self.reject('SIMULATOR_DISABLED','sim_iot_scan',dict(qr_token='x'))
        self.reject('SIMULATOR_DISABLED','sim_iot_event',{})

    def test_parking_arrival_departure_no_student_request(self):
        right = self.parking()
        self.scan(right)
        self.assertEqual(self.row('spots',right['spot_id'])['state'],'EMPTY')
        self.assertEqual(self.rows('visits')[-1]['vehicle_id'],'V3')
        self.ack('ARRIVAL')
        visit = next(v for v in self.rows('visits') if v['right_id']==right['id'])
        self.event('DEPARTURE',visit)
        self.event('DEPARTURE',visit)
        self.assertEqual(self.row('spots',right['spot_id'])['state'],'EMPTY')
        self.assertEqual(self.row('visits',visit['id'])['status'],'DEPARTED')

    def test_charging_lifecycle_and_event_replay(self):
        right = self.parking(charging=True)
        self.scan(right); self.ack('ARRIVAL')
        session = self.rows('sessions')[0]
        result = self.event('PLUG',session,event_id='connection-1')
        self.assertEqual(self.event('PLUG',session,event_id='connection-1'),result)
        self.reject('EVENT_CONFLICT','sim_iot_event',dict(kind='UNPLUG',event_id='connection-1'))
        self.assertEqual(self.row('sessions',session['id'])['status'],'START_PENDING')
        self.assertEqual(self.row('ports',session['port_id'])['power'],'OFF')
        self.assertEqual(sum(c['kind']=='START' for c in self.rows('commands')),1)
        self.ack('START')
        self.cmd('sim_observe',dict(resource_type='vehicles',resource_id='P1',soc=80),OP)
        self.assertEqual(self.row('sessions',session['id'])['status'],'STOP_PENDING')
        self.ack('STOP')
        self.assertEqual(self.row('spots',right['spot_id'])['state'],'OCCUPIED')
        self.event('UNPLUG',session)
        visit = next(v for v in self.rows('visits') if v['right_id']==right['id'])
        self.event('DEPARTURE',visit)
        self.assertEqual(self.row('spots',right['spot_id'])['state'],'EMPTY')

    def test_charging_only_approved_qr_works(self):
        request = self.cmd('submit_charge_request',dict(vehicle_id='P1',hub_id='H2',declared_soc=20,
                           target_soc=80,arrival_time=self.now))
        booked = self.cmd('approve_charge_request',dict(request_id=request['id']),OP)
        self.scan(booked,'charge_requests')
        self.assertEqual(self.row('rights',booked['right_id'])['status'],'HANDOVER_PENDING')
        self.assertEqual(self.row('sessions',booked['session_id'])['status'],'BOOKED')
        self.ack('ARRIVAL')
        self.assertEqual(self.row('rights',booked['right_id'])['status'],'CONSUMED')

    def test_scheduled_start_waits_then_issues_only_command(self):
        right = self.parking(charging=True,start=self.now+60)
        self.scan(right); self.ack('ARRIVAL')
        session = self.rows('sessions')[0]
        self.event('PLUG',session)
        self.assertEqual(self.row('sessions',session['id'])['status'],'BOOKED')
        self.now += 60
        self.service.tick()
        self.assertEqual(self.row('sessions',session['id'])['status'],'START_PENDING')
        self.assertEqual(self.row('ports',session['port_id'])['power'],'OFF')

    def test_rejected_start_does_not_create_automatic_retry_storm(self):
        right = self.parking(charging=True)
        self.scan(right); self.ack('ARRIVAL')
        session = self.rows('sessions')[0]
        self.event('PLUG',session)
        start = next(c for c in self.rows('commands') if c['kind']=='START')
        self.cmd('simulate',dict(command_id=start['id'],outcome='REJECT'),OP)
        for _ in range(3):
            self.service.tick()
        self.assertEqual(self.row('sessions',session['id'])['status'],'BOOKED')
        self.assertEqual(sum(c['kind']=='START' for c in self.rows('commands')),1)

    def test_plug_without_arrival_and_unsafe_connection_cannot_start(self):
        right = self.parking(charging=True)
        session = self.rows('sessions')[0]
        with self.assertRaises(DomainError):
            self.event('PLUG',session)
        self.assertEqual(self.rows('commands'),[])
        self.scan(right); self.ack('ARRIVAL')
        self.cmd('sim_observe',dict(resource_type='ports',resource_id=session['port_id'],health='OUT_OF_SERVICE'),OP)
        with self.assertRaises(DomainError):
            self.event('PLUG',session)
        self.assertEqual(self.row('ports',session['port_id'])['power'],'OFF')
        self.assertFalse(any(c['kind']=='START' for c in self.rows('commands')))

    def test_add_charging_uses_existing_visit_and_cancel_keeps_right(self):
        right = self.parking()
        session = self.cmd('register_charge',dict(right_id=right['id'],target_soc=80))
        self.cmd('cancel_charge',dict(session_id=session['id']))
        self.assertEqual(self.row('rights',right['id'])['status'],'CONFIRMED')
        self.scan(right); self.ack('ARRIVAL')
        session = self.cmd('register_charge',dict(right_id=right['id'],target_soc=80))
        self.event('PLUG',session)
        self.assertEqual(self.row('sessions',session['id'])['status'],'START_PENDING')
        self.assertEqual(len(self.rows('rights')),1)
        self.assertEqual(sum(v['vehicle_id']=='P1' for v in self.rows('visits')),1)

    def test_events_require_correct_scope_and_freshness(self):
        right = self.parking(charging=True)
        self.scan(right); self.ack('ARRIVAL')
        session = self.rows('sessions')[0]
        payload = dict(kind='PLUG',record_id=session['id'],vehicle_id='P1',hub_id='H2',spot_id='H2-S1',
                       port_id='H2-C1',event_id='bad-event')
        self.reject('DEVICE_SCOPE','sim_iot_event',dict(payload,port_id='H2-C2'))
        self.reject('STALE_EVENT','sim_iot_event',dict(payload,observed_at=self.now-91))
        self.assertEqual(self.row('ports','H2-C1')['plug'],'UNPLUGGED')
        self.assertEqual(self.row('sessions',session['id'])['status'],'BOOKED')

    def test_return_destination_only_then_device_handover(self):
        self.scan(self.cmd('reserve_vehicle',dict(vehicle_id='V1')),'holds'); self.ack('PICKUP')
        trip = self.rows('trips')[0]
        self.cmd('select_return_hub',dict(trip_id=trip['id'],hub_id='H2'))
        self.assertEqual(self.row('trips',trip['id'])['status'],'OPEN')
        self.assertFalse(any(c['kind']=='RETURN' for c in self.rows('commands')))
        base = dict(record_id=trip['id'],vehicle_id='V1',hub_id='H2')
        pending = self.cmd('sim_iot_event',dict(base,kind='RETURN_PREPARE',event_id='prepare'),OP)
        right = self.row('rights',pending['return_right_id'])
        self.assertEqual(self.row('trips',trip['id'])['status'],'HANDOVER_PENDING')
        payload = dict(base,kind='RETURN',event_id='return',spot_id=right['spot_id'])
        self.cmd('sim_iot_event',payload,OP)
        self.cmd('sim_iot_event',payload,OP)
        self.assertEqual(self.row('trips',trip['id'])['status'],'CLOSED')
        self.assertEqual(self.row('vehicles','V1')['hub_id'],'H2')


if __name__ == '__main__':
    unittest.main()
