"""Public commands for D01/D04/D05/D07 and their consequences in A/B/C."""
import tempfile
import unittest
import uuid
from pathlib import Path

from emobility.domain import DomainError, Service


OP = {'id': 'operator', 'role': 'operator'}
TECH = {'id': 'technician', 'role': 'technician'}
ALICE = {'id': 'alice', 'role': 'student'}


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'hub.sqlite'
        self.now = 1_800_000_000.0
        self.service = Service(self.path, simulator=True, clock=lambda: self.now)

    def run_command(self, action, actor=OP, **payload):
        return self.service.command(actor, action, payload, uuid.uuid4().hex)['record']

    def rows(self, kind, actor=OP):
        return {r['id']: r for r in self.service.snapshot(actor)[kind]}

    def rejects(self, code, action, actor=OP, **payload):
        with self.assertRaises(DomainError) as exc:
            self.run_command(action, actor, **payload)
        self.assertEqual(exc.exception.code, code)

    def open_ticket(self, resource):
        return self.run_command('d_open_incident', resource_id=resource, message='Inspect damaged equipment')

    def resolve(self, ticket):
        return self.run_command('d_update_incident', TECH, incident_id=ticket['id'], note='Safety tests passed',
                                outcome='RESOLVED', safety_passed=True)

    def test_deactivation_respects_busy_resources_and_capacity(self):
        self.run_command('reserve_vehicle', ALICE, vehicle_id='V1')
        self.rejects('RESOURCE_BUSY', 'd_resource_state', resource_id='V1', active=False)
        self.rejects('RESOURCE_BUSY', 'd_resource_state', resource_id='H1-S3', active=False)
        before = self.rows('hubs')['H3']['available']
        self.run_command('d_resource_state', resource_id='H3-S9', active=False)
        self.assertEqual(self.rows('hubs')['H3']['available'], before - 1)
        self.run_command('d_resource_state', resource_id='H3-S9', active=True)
        self.assertEqual(self.rows('hubs')['H3']['available'], before)

    def test_repair_restores_only_with_safety_and_preserves_admin_disable(self):
        self.run_command('d_resource_state', resource_id='H1-C1', active=False)
        self.rejects('FORBIDDEN', 'd_open_incident', ALICE, resource_id='H1-C1', message='Fault on charger')
        ticket = self.open_ticket('H1-C1')
        self.assertIn(ticket['id'], self.rows('incidents', TECH))
        self.rejects('ALREADY_ASSIGNED', 'd_open_incident', resource_id='H1-C1', message='Second report')
        self.rejects('REPAIR_REQUIRED', 'd_resource_state', resource_id='H1-C1', active=True)
        self.rejects('FORBIDDEN', 'd_update_incident', OP, incident_id=ticket['id'], outcome='RESOLVED',
                     note='Safety checks performed', safety_passed=True)
        self.rejects('INSPECTION_REQUIRED', 'd_update_incident', TECH, incident_id=ticket['id'],
                     outcome='RESOLVED', note='Safety checks missing', safety_passed=False)
        self.assertEqual(self.rows('ports')['H1-C1']['health'], 'OUT_OF_SERVICE')
        self.resolve(ticket)
        self.assertEqual(self.rows('ports')['H1-C1']['health'], 'DEACTIVATED')
        self.run_command('d_resource_state', resource_id='H1-C1', active=True)
        self.assertEqual(self.rows('ports')['H1-C1']['health'], 'OPERABLE')

    def test_support_can_lead_to_maintenance_without_releasing_hold(self):
        hold = self.run_command('reserve_vehicle', ALICE, vehicle_id='V1')
        issue = self.run_command('support', ALICE, record_id=hold['id'], message='Brake inspection required')
        self.rejects('INVALID_ORIGIN', 'd_open_incident', resource_id='V2', message=issue['message'],
                     origin_incident_id=issue['id'])
        ticket = self.run_command('d_open_incident', resource_id='V1', message=issue['message'],
                                  origin_incident_id=issue['id'])
        self.rejects('VEHICLE_UNAVAILABLE', 'pickup', ALICE, hold_id=hold['id'])
        self.run_command('d_update_incident', TECH, incident_id=ticket['id'], outcome='ESCALATED_WORKSHOP',
                         note='Requires workshop equipment')
        self.assertEqual(self.rows('vehicles')['V1']['health'], 'OUT_OF_SERVICE')
        self.assertEqual(self.rows('holds', ALICE)[hold['id']]['status'], 'ACTIVE')
        student_issues = self.rows('incidents', ALICE)
        self.assertIn('ESCALATED_WORKSHOP', student_issues[issue['id']]['response'])
        self.assertNotIn(ticket['id'], student_issues)

    def test_telemetry_idempotency_order_and_analytics_after_restart(self):
        packet = dict(resourceId='V1', event_id='first', batterySoc=60, speed=10, temperatureC=30)
        first = self.run_command('d_telemetry', **packet)
        self.assertEqual(first['alerts'], [])
        self.rejects('EVENT_CONFLICT', 'd_telemetry', **dict(packet, speed=99))
        self.service = Service(self.path, simulator=True, clock=lambda: self.now)
        self.now += 3
        second = self.run_command('d_telemetry', resourceId='V1', event_id='second', batterySoc=12,
                                  speed=115, temperatureC=40, destinationHubId='H2')
        self.assertEqual(set(second['alerts']), {'RAPID_DRAIN', 'THERMAL_SPIKE', 'LOW_BATTERY', 'OVERSPEED'})
        self.assertEqual(self.run_command('d_telemetry', **packet), first)
        self.rejects('STALE_EVENT', 'd_telemetry', **dict(packet, event_id='late', observed_at=self.now-2))
        self.rejects('STALE_EVENT', 'd_telemetry', **dict(packet, event_id='legacy', timestamp='2020-01-01T00:00:00Z'))
        self.rejects('STALE_EVENT', 'd_telemetry', **dict(packet, event_id='old-sequence', sequence=1))
        self.rejects('UNKNOWN_VEHICLE', 'd_telemetry', **dict(packet, event_id='unknown', resourceId='missing'))
        self.assertEqual(self.rows('vehicles')['V1']['soc'], 12)
        self.assertEqual(self.rows('vehicles')['V1']['hub_id'], 'H1')
        self.assertFalse(self.rows('vehicles')['V1']['available'])
        self.assertNotIn('last_telemetry', self.rows('vehicles', ALICE)['V1'])
        self.now += 31
        third = self.run_command('d_telemetry', **dict(packet, event_id='third', batterySoc=5, temperatureC=60))
        self.assertEqual(third['alerts'], ['LOW_BATTERY'])

    def test_telemetry_requires_enabled_simulator_and_operator(self):
        packet = dict(resourceId='V2', event_id='test', batterySoc=90)
        self.rejects('FORBIDDEN', 'd_telemetry', ALICE, **packet)
        self.service = Service(self.path, simulator=False, clock=lambda: self.now)
        self.rejects('SIMULATOR_DISABLED', 'd_telemetry', **packet)
        self.assertEqual(self.rows('vehicles')['V2']['soc'], 45)

    def test_fault_on_running_charger_requests_stop_until_ack(self):
        right = self.run_command('reserve_parking', ALICE, vehicle_id='P1', hub_id='H1', charging=True,
                                 start=self.now, end=self.now + 3600, target_soc=60)
        session = next(iter(self.rows('sessions').values()))
        for action, payload in [('arrive', {'right_id': right['id']}), ('plug', {'session_id': session['id']}),
                                ('start_charge', {'session_id': session['id']})]:
            self.run_command(action, ALICE, **payload)
            cmd = next(c for c in self.rows('commands').values() if c['status'] == 'PENDING')
            self.run_command('simulate', command_id=cmd['id'])
        ticket = self.open_ticket(session['port_id'])
        self.assertEqual(self.rows('sessions')[session['id']]['status'], 'STOP_PENDING')
        self.assertEqual(self.rows('ports')[session['port_id']]['power'], 'ON')
        self.rejects('STOP_PENDING', 'd_update_incident', TECH, incident_id=ticket['id'], note='Repair complete',
                     outcome='RESOLVED', safety_passed=True)
        stop = next(c for c in self.rows('commands').values() if c['kind'] == 'STOP')
        self.run_command('simulate', command_id=stop['id'])
        self.resolve(ticket)
        self.assertEqual(self.rows('ports')[session['port_id']]['health'], 'OPERABLE')
        self.assertEqual(self.rows('ports')[session['port_id']]['plug'], 'CONNECTED')
