"""Controlled device adapter reusing A/B/C commands and evidence validation.

This is an operator-only simulator boundary, not authenticated real hardware.
Scanning grants an intent; only separate evidence changes physical state.
"""
import hmac
import json

from .shared import DomainError, POLICY, fingerprint, number, require


class IotWorkflowMixin:
    def iot_scope(self, state, payload, vehicle_id, spot_id, port_id=None):
        spot = self.get(state, 'spots', spot_id)
        expected = dict(vehicle_id=vehicle_id, hub_id=spot['hub_id'], spot_id=spot_id)
        if port_id is not None:
            expected['port_id'] = port_id
        require(all(payload.get(key) == value for key, value in expected.items()),
                'DEVICE_SCOPE', 'Device vehicle, Hub, bay or port does not match the reservation.', 403)

    def do_select_return_hub(self, s, a, p, db, rev):
        trip = self.get(s, 'trips', p.get('trip_id'))
        self.own(trip, a)
        require(trip['status'] in ('OPEN', 'ASSISTANCE_PENDING'), 'INVALID_STATE',
                'Destination cannot change during a handover or after return.')
        hub = self.get(s, 'hubs', p.get('hub_id'))
        right_id = p.get('right_id')
        if right_id:
            right = self.get(s, 'rights', right_id)
            self.own(right, a)
            require(right['vehicle_id'] == trip['vehicle_id'] and right['hub_id'] == hub['id']
                    and right['status'] == 'CONFIRMED', 'RIGHT_MISMATCH', 'Choose a valid return right for this vehicle and Hub.')
        trip.update(selected_return_hub_id=hub['id'], selected_return_right_id=right_id)
        return trip

    def do_sim_iot_scan(self, s, a, p, db, rev):
        self.sim_guard()
        token = p.get('qr_token')
        require(isinstance(token, str) and token.isascii() and 1 <= len(token) <= 128,
                'INVALID_QR', 'A valid QR token is required.', 400)
        for collection, action, key in [('holds', 'scan_rental', 'hold_id'),
                                       ('charge_requests', 'scan_charge', 'request_id'),
                                       ('rights', 'arrive', 'right_id')]:
            record = next((r for r in s[collection].values()
                           if hmac.compare_digest(r.get('qr', {}).get('token', ''), token)), None)
            if record is None:
                continue
            vehicle = s['vehicles'][record['vehicle_id']]
            if collection == 'holds':
                spot_id = vehicle['spot_id']
                require(record.get('pickup_hub_id') == p.get('hub_id'), 'DEVICE_SCOPE', 'Wrong pickup Hub.', 403)
            else:
                right = s['rights'][record['right_id']] if collection == 'charge_requests' else record
                spot_id = right['spot_id']
            self.iot_scope(s, p, vehicle['id'], spot_id)
            owner = dict(id=record['owner_id'], role='student')
            result = getattr(self, 'do_'+action)(s, owner, {key: record['id'], 'qr_token': token}, db, rev)
            if collection != 'holds':
                right['iot_managed'] = True
                for session in s['sessions'].values():
                    if session['right_id'] == right['id']:
                        session['iot_managed'] = True
            return dict(result, evidence='SIMULATED', verification='QR_ONLY_AWAITING_PHYSICAL_EVIDENCE')
        raise DomainError('INVALID_QR', 'QR token is not recognized.', 400)

    def do_sim_iot_event(self, s, a, p, db, rev):
        self.sim_guard()
        event_id = p.get('event_id')
        require(isinstance(event_id, str) and 1 <= len(event_id) <= 128,
                'INVALID_INPUT', 'Provide a durable event_id for retry.', 400)
        fp = fingerprint(p)
        previous = db.execute('SELECT fingerprint,result FROM events WHERE source=? AND id=?',
                              ('IOT_SIMULATOR', event_id)).fetchone()
        if previous:
            require(previous[0] == fp, 'EVENT_CONFLICT', 'Event identity reused with different evidence.')
            return json.loads(previous[1])
        observed = number(p.get('observed_at', self.clock()), 'observed_at')
        require(self.clock()-POLICY['freshness'] <= observed <= self.clock()+5,
                'STALE_EVENT', 'Device event is stale or future-dated.')
        kind = p.get('kind')
        require(kind in ('PLUG', 'UNPLUG', 'DEPARTURE', 'RETURN', 'RETURN_PREPARE'),
                'INVALID_INPUT', 'Unsupported device event.', 400)
        collection = 'sessions' if kind in ('PLUG', 'UNPLUG') else ('visits' if kind == 'DEPARTURE' else 'trips')
        record = self.get(s, collection, p.get('record_id'))
        owner = dict(id=record['owner_id'], role='student')
        if collection == 'trips':
            require(p.get('vehicle_id') == record['vehicle_id'] and
                    p.get('hub_id') == record.get('selected_return_hub_id'),
                    'DEVICE_SCOPE', 'Device must match the vehicle and selected return Hub.', 403)
            if record['status'] == 'CLOSED':
                right = s['rights'][record['return_right_id']]
                self.iot_scope(s, p, record['vehicle_id'], right['spot_id'])
                result = dict(status='ALREADY_APPLIED', evidence='SIMULATED')
            else:
                params = dict(trip_id=record['id'], hub_id=record['selected_return_hub_id'],
                              right_id=record.get('selected_return_right_id'))
                self.do_return_vehicle(s, owner, params, db, rev)
                if kind == 'RETURN_PREPARE' or record['status'] == 'ASSISTANCE_PENDING':
                    result = dict(record, evidence='SIMULATED', verification='RECEPTION_NOT_CONFIRMED')
                else:
                    right = s['rights'][record['return_right_id']]
                    self.iot_scope(s, p, record['vehicle_id'], right['spot_id'])
                    result = self.iot_ack(s, a, p, db, rev, 'RETURN', record, observed)
        else:
            port = s['ports'][record['port_id']] if collection == 'sessions' else None
            spot_id = port['spot_id'] if port else record['spot_id']
            self.iot_scope(s, p, record['vehicle_id'], spot_id, port['id'] if port else None)
            for resource in (s['vehicles'][record['vehicle_id']], s['spots'][spot_id], port):
                if resource:
                    require(observed >= (resource.get('observed_at') or 0), 'STALE_EVENT',
                            'Event predates resource observation.')
            already = (kind == 'DEPARTURE' and record['status'] == 'DEPARTED') or (
                kind == 'PLUG' and port['plug'] == 'CONNECTED' and port['vehicle_id'] == record['vehicle_id']) or (
                kind == 'UNPLUG' and port['plug'] == 'UNPLUGGED' and any(c['kind'] == 'UNPLUG'
                    and c['record_id'] == record['id'] and c['status'] == 'ACKNOWLEDGED' for c in s['commands'].values()))
            if already:
                if kind == 'PLUG' and record['status'] == 'BOOKED':
                    record['iot_managed'] = True
                    record['iot_start_requested'] = False
                result = dict(status='ALREADY_APPLIED', evidence='SIMULATED')
            else:
                action, key = {'PLUG': ('plug', 'session_id'), 'UNPLUG': ('unplug', 'session_id'),
                               'DEPARTURE': ('depart', 'visit_id')}[kind]
                getattr(self, 'do_'+action)(s, owner, {key:record['id']}, db, rev)
                if kind == 'PLUG':
                    record['iot_managed'] = True
                    record['iot_start_requested'] = False
                result = self.iot_ack(s, a, p, db, rev, kind, record, observed)
        db.execute('INSERT INTO events VALUES(?,?,?,?,?)', ('IOT_SIMULATOR', event_id, fp,
                   json.dumps(dict(p, evidence='SIMULATED')), json.dumps(result)))
        return result

    def iot_ack(self, s, actor, payload, db, rev, kind, record, observed):
        command = next(c for c in s['commands'].values() if c['kind'] == kind
                       and c['record_id'] == record['id'] and c['status'] == 'PENDING')
        # Sensor-driven initiation and acknowledgement share a transaction; the
        # observation may precede command creation by milliseconds. Reject old
        # resource evidence here, then stamp the acknowledgement at receipt time.
        for collection, key in [('vehicles','vehicle_id'), ('spots','spot_id'), ('ports','port_id')]:
            resource = s[collection].get(command.get(key))
            if resource:
                require(observed >= (resource.get('observed_at') or 0), 'STALE_EVENT', 'Event predates resource observation.')
        return self.do_simulate(s, actor, dict(command_id=command['id'],
            event_id='iot:'+fingerprint(payload['event_id']), outcome='ACK', observed_at=max(observed, command['created_at']),
            **{key:payload[key] for key in ('vehicle_id','spot_id','port_id')
               if payload.get(key) and command.get(key) is not None}), db, rev)

    def advance_iot_charging(self, s):
        """Initiate power command only; the existing ACK still gates CHARGING."""
        for session in s['sessions'].values():
            if not session.get('iot_managed') or session.get('iot_start_requested') or session['status'] != 'BOOKED':
                continue
            port = s['ports'][session['port_id']]
            if port['plug'] != 'CONNECTED' or port.get('vehicle_id') != session['vehicle_id']:
                continue
            try:
                self.do_start_charge(s, dict(id=session['owner_id'], role='student'),
                                     dict(session_id=session['id']), None, None)
                session['iot_start_requested'] = True
            except DomainError:
                # Existing schedule/freshness/power/health gates remain authoritative.
                # A later maintenance tick retries readiness without inventing ACK.
                pass
