"""Operations on the same resources and transactions used by rentals, parking and charging.

Adapted from the submitted D NetworkMonitoringController, IncidentController,
TelemetryController and StreamAnalyticsProcessor. Occupancy is computed by B.
Inspections are staff reports. Telemetry comes from the controlled simulator.
"""
import json
from datetime import datetime

from .shared import DomainError, LIVE_RIGHT, LIVE_SESSION, POLICY, fingerprint, number, require


def find_resource(state, resource_id):
    require(isinstance(resource_id, str), 'INVALID_INPUT', 'Select a resource.', 400)
    for collection in ('vehicles', 'ports', 'spots'):
        if resource_id in state[collection]:
            return collection, state[collection][resource_id]
    require(False, 'NOT_FOUND', 'Resource does not exist.', 404)


def note_text(value, name):
    require(isinstance(value, str) and 5 <= len(value.strip()) <= 2000,
            'INVALID_INPUT', f'{name} must contain 5–2000 characters.', 400)
    return value.strip()


def associated_sessions(state, collection, resource_id):
    for session in state['sessions'].values():
        port = state['ports'][session['port_id']]
        identifiers = {'vehicles': session['vehicle_id'], 'ports': port['id'], 'spots': port['spot_id']}
        if session['status'] in LIVE_SESSION and identifiers[collection] == resource_id:
            yield session


def associated_ports(state, collection, row):
    if collection == 'ports':
        return [row]
    if collection == 'spots':
        return [p for p in state['ports'].values() if p['spot_id'] == row['id']]
    return [p for p in state['ports'].values() if p['vehicle_id'] == row['id']]


def incident_concerns(state, incident, resource_id):
    record_id = incident['record_id']
    if record_id == resource_id:
        return True
    for collection in ('holds', 'trips', 'rights', 'visits', 'sessions', 'commands'):
        record = state[collection].get(record_id, {})
        if resource_id in (record.get('vehicle_id'), record.get('spot_id'), record.get('port_id')):
            return True
    return False


def packet_alerts(previous, packet):
    # Thresholds and oldest-to-newest sliding-window comparison from the D submission.
    alerts = []
    if packet['batterySoc'] < 15:
        alerts.append('LOW_BATTERY')
    if packet['speed'] is not None and packet['speed'] > 100:
        alerts.append('OVERSPEED')
    if previous and packet['observed_at'] - previous['observed_at'] > 1:
        if previous['batterySoc'] - packet['batterySoc'] >= 4:
            alerts.append('RAPID_DRAIN')
        temperatures = previous.get('temperatureC'), packet['temperatureC']
        if None not in temperatures and temperatures[1] - temperatures[0] >= 6:
            alerts.append('THERMAL_SPIKE')
    return alerts


class MonitoringMixin:
    def resource_in_use(self, state, collection, row):
        rid = row['id']
        if collection == 'vehicles' and (self.vehicle_claimed(state, rid) or row.get('transfer_order_id')):
            return True
        if collection == 'spots' and row['state'] != 'EMPTY':
            return True
        ports = associated_ports(state, collection, row)
        if any(p['plug'] != 'UNPLUGGED' or p['power'] != 'OFF' for p in ports):
            return True
        if any(associated_sessions(state, collection, rid)):
            return True
        claim_field = 'vehicle_id' if collection == 'vehicles' else 'spot_id'
        claimed_id = row['spot_id'] if collection == 'ports' else rid
        if any(right['status'] in LIVE_RIGHT and right[claim_field] == claimed_id
               for right in state['rights'].values()):
            return True
        return any(c['status'] == 'PENDING' and rid in (c.get('vehicle_id'), c.get('spot_id'), c.get('port_id'))
                   for c in state['commands'].values())

    def do_d_resource_state(self, s, a, p, db, rev):
        require(a['role'] == 'operator', 'FORBIDDEN', 'Operator role required.', 403)
        collection, row = find_resource(s, p.get('resource_id'))
        active = p.get('active')
        require(type(active) is bool, 'INVALID_INPUT', 'active must be boolean.', 400)
        require(not row.get('maintenance_ticket_id'), 'REPAIR_REQUIRED', 'An assigned repair is outstanding.')
        if active:
            require(row['health'] == 'DEACTIVATED', 'INVALID_STATE', 'Only a deactivated resource can be enabled.')
            row['health'] = 'OPERABLE'
        else:
            require(row['health'] == 'OPERABLE', 'INVALID_STATE', 'Resource is already unavailable.')
            require(self.fresh(row, self.clock()) and not self.resource_in_use(s, collection, row),
                    'RESOURCE_BUSY', 'Current observations must show an idle, unclaimed resource.')
            row['health'] = 'DEACTIVATED'
        return row

    def do_d_open_incident(self, s, a, p, db, rev):
        require(a['role'] == 'operator', 'FORBIDDEN', 'Operator role required.', 403)
        collection, row = find_resource(s, p.get('resource_id'))
        message = note_text(p.get('message'), 'Issue description')
        technician = p.get('technician_id', 'technician')
        require(technician == 'technician', 'UNKNOWN_TECHNICIAN', 'Unknown maintenance technician.', 400)
        require(not row.get('maintenance_ticket_id'), 'ALREADY_ASSIGNED', 'Resource has an outstanding repair.')
        origin = None
        if p.get('origin_incident_id') is not None:
            origin = self.get(s, 'incidents', p['origin_incident_id'])
            require(origin['status'] in ('OPEN', 'WAITING_FOR_D') and not origin.get('maintenance_ticket_id')
                    and incident_concerns(s, origin, row['id']), 'INVALID_ORIGIN',
                    'Select an open incident concerning this resource.')
        ticket = self.new(s, 'incidents', kind='MAINTENANCE', owner_id='operator', technician_id=technician,
                          resource_id=row['id'], record_id=row['id'], message=message, status='OPEN',
                          response='', created_at=self.clock(), reported_by=a['id'],
                          previous_health=row['health'], origin_incident_id=origin['id'] if origin else None)
        row.update(health='OUT_OF_SERVICE', maintenance_ticket_id=ticket['id'])
        if origin:
            origin.update(maintenance_ticket_id=ticket['id'], response='Assigned to maintenance.')
        for session in associated_sessions(s, collection, row['id']):
            self.incident(s, session['owner_id'], session['id'], 'Charging equipment or vehicle requires maintenance.',
                          'charge-fault-' + session['id'])
            if session['status'] in ('START_PENDING', 'CHARGING', 'STOP_PENDING'):
                session['status'] = 'STOP_PENDING'
                self.request(s, 'STOP', session, session['owner_id'],
                             port_id=session['port_id'], vehicle_id=session['vehicle_id'])
        return ticket

    def do_d_update_incident(self, s, a, p, db, rev):
        require(a['role'] == 'technician', 'FORBIDDEN', 'Assigned technician required.', 403)
        ticket = self.get(s, 'incidents', p.get('incident_id'))
        require(ticket.get('kind') == 'MAINTENANCE' and ticket.get('technician_id') == a['id'],
                'FORBIDDEN', 'This repair is not assigned to you.', 403)
        require(ticket['status'] == 'OPEN', 'INVALID_STATE', 'Only an open repair can be updated.')
        collection, row = find_resource(s, ticket['resource_id'])
        require(row.get('maintenance_ticket_id') == ticket['id'] and row['health'] == 'OUT_OF_SERVICE',
                'INVALID_STATE', 'Resource and ticket do not match.')
        outcome = p.get('outcome')
        require(outcome in ('RESOLVED', 'ESCALATED_WORKSHOP'), 'INVALID_INPUT', 'Select a repair outcome.', 400)
        note = note_text(p.get('note'), 'Repair report')
        if outcome == 'RESOLVED':
            require(p.get('safety_passed') is True, 'INSPECTION_REQUIRED', 'A successful safety inspection is required.')
            require(all(port['power'] == 'OFF' for port in associated_ports(s, collection, row))
                    and all(session['status'] == 'BOOKED' for session in associated_sessions(s, collection, row['id'])),
                    'STOP_PENDING', 'Charging must stop before the repair can be cleared.')
            row['health'] = 'DEACTIVATED' if ticket['previous_health'] == 'DEACTIVATED' else 'OPERABLE'
            row.pop('maintenance_ticket_id')
        ticket.update(status=outcome, response=note, updated_at=self.clock(), updated_by=a['id'],
                      safety_passed=outcome == 'RESOLVED', evidence='TECHNICIAN_REPORT')
        origin = s['incidents'].get(ticket['origin_incident_id'])
        if origin:
            origin['response'] = f'{outcome}: {note}'
            # A repair does not acknowledge a pending journey or parking handover.
            if outcome == 'RESOLVED' and origin['record_id'] == row['id']:
                origin['status'] = 'RESOLVED'
        return ticket

    def do_d_telemetry(self, s, a, p, db, rev):
        require(a['role'] == 'operator', 'FORBIDDEN', 'Operator role required for the simulator.', 403)
        self.sim_guard()
        event_id = p.get('event_id')
        require(isinstance(event_id, str) and 1 <= len(event_id) <= 128,
                'INVALID_INPUT', 'An event_id (1–128 characters) is required.', 400)
        fp = fingerprint(p)
        source = 'D_SIM_TELEMETRY'
        old = db.execute('SELECT fingerprint,result FROM events WHERE source=? AND id=?', (source, event_id)).fetchone()
        if old:
            require(old[0] == fp, 'EVENT_CONFLICT', 'Event identity already has a different payload.')
            return json.loads(old[1])

        vid = p.get('resourceId')
        require(isinstance(vid, str) and vid in s['vehicles'], 'UNKNOWN_VEHICLE', 'Unknown telemetry vehicle.', 400)
        vehicle = s['vehicles'][vid]
        now = self.clock()
        observed = number(p.get('observed_at', now), 'observed_at')
        if 'timestamp' in p:
            # The submitted D simulator emits an ISO timestamp in local time.
            try:
                legacy_time = datetime.fromisoformat(p['timestamp'].replace('Z', '+00:00')).timestamp()
            except (AttributeError, TypeError, ValueError, OverflowError, OSError):
                raise DomainError('INVALID_INPUT', 'timestamp must be an ISO date and time.', 400)
            require('observed_at' not in p or abs(observed - legacy_time) < 0.001,
                    'INVALID_INPUT', 'Packet timestamps disagree.', 400)
            observed = legacy_time
        sequence = number(p.get('sequence', vehicle['sequence'] + 1), 'sequence', 1)
        require(sequence.is_integer(), 'INVALID_INPUT', 'sequence must be an integer.', 400)
        require(now - POLICY['freshness'] <= observed <= now + 5 and observed >= (vehicle['observed_at'] or 0)
                and sequence > vehicle['sequence'], 'STALE_EVENT', 'Stale or out-of-order telemetry.')
        destination = p.get('destinationHubId')
        if destination is not None:
            self.get(s, 'hubs', destination)
        packet = dict(resourceId=vid, event_id=event_id, observed_at=observed, sequence=int(sequence),
                      batterySoc=number(p.get('batterySoc'), 'batterySoc', 0, 100), destinationHubId=destination,
                      speed=number(p['speed'], 'speed', 0, 500) if 'speed' in p else None,
                      temperatureC=number(p['temperatureC'], 'temperatureC', -80, 250) if 'temperatureC' in p else None,
                      evidence='SIMULATED')
        # Read history by event time so the 30 s window survives process restarts.
        db.execute("""CREATE INDEX IF NOT EXISTS d_telemetry_window
                      ON events(json_extract(body,'$.resourceId'), json_extract(body,'$.observed_at'))
                      WHERE source='D_SIM_TELEMETRY'""")
        previous = db.execute("""SELECT body FROM events WHERE source='D_SIM_TELEMETRY'
                               AND json_extract(body,'$.resourceId')=?
                               AND json_extract(body,'$.observed_at') BETWEEN ? AND ?
                               ORDER BY json_extract(body,'$.observed_at'), rowid LIMIT 1""",
                              (vid, observed - 30, observed)).fetchone()
        alerts = packet_alerts(json.loads(previous[0]) if previous else None, packet)
        for key in alerts:
            self.incident(s, 'operator', vid, f'{vid}: {key} (simulated telemetry).', f'telemetry-{vid}-{key}')
        if vehicle['hub_id']:
            hub = vehicle['hub_id']
            cap = self.capacity(s, hub, now, now + 1)
            if cap['level'] != 'NORMAL':
                label = 'CAPACITY_' + cap['level']
                self.incident(s, 'operator', hub, f"{hub}: {cap['effective_percent']}% effective occupancy.", f'{hub}-{label}')
                alerts.append(label)
        packet['alerts'] = alerts
        vehicle.update(soc=packet['batterySoc'], observed_at=observed, sequence=int(sequence),
                       evidence='SIMULATED', last_telemetry=packet)
        raw = json.dumps(packet, allow_nan=False)
        db.execute('INSERT INTO events VALUES(?,?,?,?,?)', (source, event_id, fp, raw, raw))
        return packet
