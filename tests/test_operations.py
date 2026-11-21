"""D02/D03/D06 integration at the same command boundary used by the web client."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest
from uuid import uuid4

from emobility.domain import DomainError, Service

OP = {'id': 'operator', 'role': 'operator'}
DC = {'id': 'dispatcher', 'role': 'dispatcher'}
ALICE = {'id': 'alice', 'role': 'student'}


class RedistributionTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.now = 1800000000.
        self.path = Path(folder.name, 'hub.sqlite')
        self.service = Service(self.path, simulator=True, clock=lambda: self.now)

    def action(self, name, payload=None, actor=OP, intent=None):
        return self.service.command(actor, name, payload or {}, intent or uuid4().hex)['record']

    def rows(self, kind, actor=OP):
        return {r['id']: r for r in self.service.snapshot(actor)[kind]}

    def draft(self, **fields):
        return self.action('transfer_preview', dict({
            'staff_id': 'dispatcher', 'source_hub_id': 'H1', 'dest_hub_id': 'H3',
            'vehicle_ids': ['V1', 'V3']
        }, **fields))

    def issue(self):
        draft = self.draft()
        return self.action('transfer_issue', {'order_id': draft['id']})

    def request_batch(self, order, selected):
        self.action('transfer_handover', {'order_id': order['id'], 'vehicle_ids': selected}, DC)
        return {cmd['vehicle_id']: cmd['id'] for cmd in self.rows('commands').values()
                if cmd['kind'] == 'TRANSFER' and cmd['status'] == 'PENDING'}

    def test_partial_handover_preserves_capacity_and_inventory_across_restart(self):
        order = self.issue()
        self.assertEqual(self.rows('hubs')['H3']['held'], 2)
        self.assertFalse(self.rows('vehicles', ALICE)['V1']['available'])
        self.assertFalse(self.rows('orders', ALICE))
        with self.assertRaises(DomainError):
            self.action('transfer_start', {'order_id': order['id']}, OP)
        self.action('transfer_start', {'order_id': order['id']}, DC)
        commands = self.request_batch(order, ['V1', 'V3'])
        self.assertEqual(len(commands), 2)
        self.assertEqual(self.rows('vehicles')['V1']['hub_id'], 'H1')
        # Loss/duplicate replay cannot release the outstanding truckload.
        uncertain = self.action('simulate', {'command_id': commands['V3'], 'outcome': 'UNKNOWN'})
        self.assertEqual(uncertain['status'], 'PENDING')
        event = {'command_id': commands['V1'], 'event_id': 'arrival-1'}
        first = self.action('simulate', event)
        self.assertEqual(first['status'], 'ACKNOWLEDGED')
        self.assertEqual(self.action('simulate', event), first)
        self.service = Service(self.path, simulator=True, clock=lambda: self.now)
        partial = self.rows('orders', DC)[order['id']]
        self.assertEqual((partial['status'], partial['delivered'], partial['pending']),
                         ('IN_PROGRESS', ['V1'], ['V3']))
        self.assertEqual(self.rows('hubs')['H3']['held'], 1)
        self.assertTrue(self.rows('vehicles', ALICE)['V1']['available'])
        self.assertEqual(self.rows('spots')['H1-S3']['state'], 'EMPTY')
        self.assertEqual(self.rows('vehicles')['V1']['hub_id'], 'H3')
        self.assertFalse(self.rows('vehicles', ALICE)['V3']['available'])
        self.assertEqual(self.rows('vehicles')['V3']['hub_id'], 'H1')
        self.action('simulate', {'command_id': commands['V3']})
        self.assertEqual(self.rows('orders')[order['id']]['status'], 'COMPLETED')
        self.assertEqual(self.rows('hubs')['H3']['held'], 0)
        self.assertEqual(self.rows('hubs')['H3']['occupied'], 2)
        self.assertEqual(self.rows('hubs')['H1']['occupied'], 0)

    def test_preview_issue_race_with_rental_is_atomic(self):
        order = self.draft()
        self.assertFalse(self.rows('rights'))
        barrier = threading.Barrier(2)

        def race(action, payload, actor):
            other = Service(self.path, simulator=True, clock=lambda: self.now)
            barrier.wait()
            try:
                other.command(actor, action, payload, uuid4().hex)
                return True
            except DomainError:
                return False

        with ThreadPoolExecutor(max_workers=2) as executor:
            transfer = executor.submit(race, 'transfer_issue', {'order_id': order['id']}, OP)
            rental = executor.submit(race, 'reserve_vehicle', {'vehicle_id': 'V3'}, ALICE)
        self.assertNotEqual(transfer.result(), rental.result())
        won_transfer = self.rows('orders')[order['id']]['status'] == 'ISSUED'
        self.assertEqual(won_transfer, transfer.result())
        self.assertEqual(self.rows('hubs')['H3']['held'], 2 if won_transfer else 0)
        self.assertEqual(self.rows('vehicles')['V1']['available'], not won_transfer)

    def test_rejected_handover_can_retry_after_destination_recovers(self):
        order = self.issue()
        self.action('transfer_start', {'order_id': order['id']}, DC)
        command = self.request_batch(order, ['V1'])['V1']
        # Resource fails after the staff submits the request.
        spot = self.rows('rights')[order['rights']['V1']]['spot_id']
        observation = {'resource_type': 'spots', 'resource_id': spot, 'health': 'OUT_OF_SERVICE'}
        self.action('sim_observe', observation)
        self.assertEqual(self.action('simulate', {'command_id': command})['status'], 'ANOMALY')
        self.assertEqual(self.rows('vehicles')['V1']['hub_id'], 'H1')
        self.assertEqual(self.rows('orders')[order['id']]['pending'], ['V1'])
        self.action('simulate', {'command_id': command, 'outcome': 'REJECT'})
        self.assertEqual(self.rows('orders')[order['id']]['pending'], [])
        self.action('sim_observe', dict(observation, health='OPERABLE'))
        new_command = self.request_batch(order, ['V1'])['V1']
        self.assertNotEqual(new_command, command)
        self.assertEqual(self.action('simulate', {'command_id': new_command})['status'], 'ACKNOWLEDGED')

    def test_transfer_to_charging_bay_allows_c_to_book_and_run_fleet_charge(self):
        self.action('sim_observe', {'resource_type': 'vehicles', 'resource_id': 'V1', 'soc': 12})
        self.assertFalse(self.rows('vehicles', ALICE)['V1']['available'])
        self.assertTrue(self.rows('vehicles')['V1']['transferable'])
        draft = self.draft(charging_bays=True, vehicle_ids=['V1'])
        order = self.action('transfer_issue', {'order_id': draft['id']})
        payload = {'vehicle_id': 'V1', 'target_soc': 90}
        with self.assertRaises(DomainError):
            self.action('fleet_charge', payload)
        self.action('transfer_start', {'order_id': order['id']}, DC)
        command = self.request_batch(order, ['V1'])['V1']
        self.action('simulate', {'command_id': command})
        self.assertFalse(self.rows('sessions'))
        session = self.action('fleet_charge', payload)
        self.assertEqual(session['port_id'], 'H3-C1')
        for action_name, expected_kind in [('plug', 'PLUG'), ('start_charge', 'START')]:
            self.action(action_name, {'session_id': session['id']})
            device_cmd = next(c for c in self.rows('commands').values()
                              if c['kind'] == expected_kind and c['record_id'] == session['id'])
            self.assertEqual(self.action('simulate', {'command_id': device_cmd['id']})['status'],
                             'ACKNOWLEDGED')
        self.assertEqual(self.rows('sessions')[session['id']]['status'], 'CHARGING')
        self.assertFalse(self.rows('vehicles')['V1']['available'])

    def test_invalid_selections_and_staff_do_not_write_partial_claims(self):
        for fields in [{'vehicle_ids': ['V1', 'V1']}, {'vehicle_ids': ['V1', 'V2']},
                       {'vehicle_ids': []}, {'dest_hub_id': 'H1'}, {'staff_id': 'alice'}]:
            with self.subTest(fields=fields), self.assertRaises(DomainError):
                self.draft(**fields)
        self.assertFalse(self.rows('orders'))
        order = self.issue()
        with self.assertRaisesRegex(DomainError, 'dispatcher'):
            self.draft(source_hub_id='H2', vehicle_ids=['V2'])
        self.action('transfer_start', {'order_id': order['id']}, DC)
        with self.assertRaises(DomainError):
            self.request_batch(order, ['V1', 'V2'])
        self.assertFalse(self.rows('commands'))
        self.assertFalse(self.rows('orders')[order['id']]['pending'])
        self.now += 1200
        self.service.tick()
        self.assertTrue(all(r['status'] == 'HANDOVER_PENDING' for r in self.rows('rights').values()))
        self.assertFalse(self.rows('vehicles')['V1']['available'])

    def test_what_if_uses_recent_distinct_inbound_telemetry(self):
        for vid in ('V1', 'V2', 'V1'):
            self.action('d_telemetry', dict(resourceId=vid, event_id=uuid4().hex,
                                           batterySoc=65, destinationHubId='H3'))
        scenario = self.action('what_if', {'hub_id': 'H3', 'demand_factor': 2})
        self.assertEqual((scenario['baseline_source'], scenario['baseline_vehicles']),
                         ('RECENT_TELEMETRY', 2))
        projected = next(h['projected_percent'] for h in scenario['impact'] if h['hub_id'] == 'H3')
        self.assertEqual(projected, 40)
        self.now += 61
        scenario = self.action('what_if', {'hub_id': 'H3', 'demand_factor': 2})
        self.assertEqual(scenario['baseline_source'], 'SCENARIO_DEFAULT')

    def test_what_if_draft_isolated_until_issue_and_revalidated(self):
        before = self.service.snapshot(OP)
        scenario = self.action('what_if', {'hub_id': 'H1', 'demand_factor': 3})
        after = self.service.snapshot(OP)
        for collection in ('vehicles', 'spots', 'ports', 'rights', 'orders', 'visits', 'holds'):
            self.assertEqual(before[collection], after[collection])
        self.assertEqual(scenario['baseline_source'], 'SCENARIO_DEFAULT')
        self.assertTrue(scenario['recommendations'])
        self.assertFalse(self.rows('scenarios', DC))
        payload = {'scenario_id': scenario['id'], 'recommendation_index': 0}
        with self.assertRaises(DomainError):
            self.action('what_if_draft', dict(payload, recommendation_index=-1))
        with self.assertRaises(DomainError):
            self.action('what_if_draft', payload, ALICE)
        draft = self.action('what_if_draft', payload)
        self.assertEqual(draft['status'], 'DRAFT')
        self.assertEqual(self.rows('hubs')[draft['dest_hub_id']]['held'], 0)
        self.action('reserve_vehicle', {'vehicle_id': draft['vehicle_ids'][-1]}, ALICE)
        with self.assertRaises(DomainError):
            self.action('transfer_issue', {'order_id': draft['id']})
        self.assertEqual(self.rows('orders')[draft['id']]['status'], 'DRAFT')
        self.assertFalse(self.rows('rights'))


if __name__ == '__main__':
    unittest.main()
