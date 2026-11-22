"""Approval of charging-only requests; allocation never implies physical evidence."""
import copy
import hmac
import secrets

from .parking_qr import qr_svg
from .shared import DomainError, POLICY, number, require


class ChargingRequestsMixin:
    def charge_request_vehicle(self, s, actor, payload):
        require(actor['role'] == 'student', 'FORBIDDEN', 'Student role required.', 403)
        vehicle = self.get(s, 'vehicles', payload.get('vehicle_id'))
        self.own(vehicle, actor)
        require(vehicle['kind'] == 'personal', 'PERSONAL_VEHICLE_REQUIRED', 'Choose your personal vehicle.')
        require(vehicle['health'] == 'OPERABLE' and not vehicle.get('spot_id'),
                'VEHICLE_UNAVAILABLE', 'Vehicle must be operational and not already parked.')
        return vehicle

    def allocate_charge_request(self, state, request):
        """Reuse existing constraints at the requested arrival, never silently delay."""
        vehicle = dict(state['vehicles'][request['vehicle_id']], soc=request['declared_soc'])
        hub = self.get(state, 'hubs', request['hub_id'])
        require(hub['open'], 'HUB_CLOSED', 'Hub is closed to new allocations.')
        now = self.clock()
        require(now - 60 <= request['arrival_time'] <= now + POLICY['max_advance'],
                'INVALID_WINDOW', 'Arrival must be now or within 24 hours.', 400)
        boundaries = {max(now, request['arrival_time'])}
        last_error = DomainError('NO_PORT', 'No compatible charging port is available.')
        for start in sorted(boundaries):
            for port in sorted(state['ports'].values(), key=lambda row: row['id']):
                if port['hub_id'] != hub['id'] or port['connector'] != vehicle['connector']:
                    continue
                kw = min(port['kw'], hub['power_kw'])
                if kw <= 0:
                    last_error = DomainError('NO_POWER', 'No charging power is available at this Hub.')
                    continue
                duration = (request['target_soc'] - request['declared_soc']) / 100 * vehicle['battery_kwh'] / (kw * POLICY['efficiency']) * 3600
                end = start + max(POLICY['min_parking'], duration)
                candidate = copy.deepcopy(state)
                try:
                    right = self.allocate_right(candidate, request['owner_id'], vehicle, hub['id'], start, end,
                                                charging=True, spot_id=port['spot_id'])
                    session = self.create_charge(candidate, {'id': request['owner_id'], 'role': 'student'},
                                                 vehicle, right, request['target_soc'], scheduled_start=start)
                except DomainError as exc:
                    last_error = exc
                    continue
                right['charge_request_id'] = request['id']
                right['reservation_type'] = 'CHARGING_ONLY'
                session.update(charge_request_id=request['id'], declared_soc=request['declared_soc'],
                               soc_source='USER_DECLARED', reservation_type='CHARGING_ONLY')
                state.clear()
                state.update(candidate)
                return dict(right_id=right['id'], session_id=session['id'], spot_id=right['spot_id'],
                            port_id=session['port_id'], scheduled_start=session['scheduled_start'],
                            scheduled_end=session['scheduled_end'], parking_end=right['end'],
                            duration=session['duration'], kw=session['kw'], available=True,
                            energy_kwh=(request['target_soc']-request['declared_soc'])/100*vehicle['battery_kwh'],
                            expected_collection_at=session['scheduled_end'])
        raise last_error

    def do_submit_charge_request(self, s, a, p, db, rev):
        vehicle = self.charge_request_vehicle(s, a, p)
        hub = self.get(s, 'hubs', p.get('hub_id'))
        require(hub['open'], 'HUB_CLOSED', 'Hub is closed to new requests.')
        declared = number(p.get('declared_soc'), 'Declared current SOC', 0, 100)
        target = number(p.get('target_soc'), 'Target SOC', 0, 100)
        arrival = number(p.get('arrival_time'), 'Arrival time')
        require(self.clock()-60 <= arrival <= self.clock()+POLICY['max_advance'],
                'INVALID_WINDOW', 'Arrival must be now or within 24 hours.', 400)
        require(target > declared, 'INVALID_TARGET', 'Target SOC must exceed declared current SOC.', 400)
        require(not any(r['vehicle_id'] == vehicle['id'] and r['status'] in ('PENDING', 'BOOKED')
                        for r in s['charge_requests'].values()), 'CHARGE_REQUEST_EXISTS', 'This vehicle already has an active charging request.')
        require(not self.charge_blocked(s, vehicle['id']), 'CHARGE_CONFLICT', 'Vehicle already has a charging commitment.')
        request = self.new(s, 'charge_requests', owner_id=a['id'], vehicle_id=vehicle['id'], hub_id=hub['id'],
                           declared_soc=declared, target_soc=target, soc_source='USER_DECLARED',
                           arrival_time=arrival, battery_kwh=vehicle['battery_kwh'], connector=vehicle['connector'],
                           reservation_type='CHARGING_ONLY',
                           status='PENDING', created_at=self.clock())
        try:
            proposal = self.allocate_charge_request(copy.deepcopy(s), request)
            proposal.pop('right_id'); proposal.pop('session_id')
            request['proposal'] = proposal
        except DomainError as exc:
            request['proposal'] = dict(available=False, reason=exc.message, code=exc.code)
        return request

    def do_approve_charge_request(self, s, a, p, db, rev):
        require(a['role'] == 'operator', 'FORBIDDEN', 'Operator role required.', 403)
        request = self.get(s, 'charge_requests', p.get('request_id'))
        if request['status'] == 'BOOKED':
            return request
        require(request['status'] == 'PENDING', 'INVALID_STATE', 'Only pending requests can be approved.')
        self.charge_request_vehicle(s, {'id': request['owner_id'], 'role': 'student'}, request)
        allocation = self.allocate_charge_request(s, request)
        # Allocator replaces state with its successful transactional candidate.
        request = s['charge_requests'][request['id']]
        request.update(allocation, status='BOOKED', approved_by=a['id'], approved_at=self.clock())
        request['qr'] = dict(token='emobility:charging:' + secrets.token_urlsafe(32),
                             issued_at=self.clock(), expires_at=allocation['scheduled_start'] + POLICY['no_show'])
        return request

    def do_reject_charge_request(self, s, a, p, db, rev):
        require(a['role'] == 'operator', 'FORBIDDEN', 'Operator role required.', 403)
        request = self.get(s, 'charge_requests', p.get('request_id'))
        require(request['status'] == 'PENDING', 'INVALID_STATE', 'Only pending requests can be rejected.')
        reason = p.get('reason')
        require(isinstance(reason, str) and 1 <= len(reason.strip()) <= 2000,
                'INVALID_INPUT', 'A rejection reason is required.', 400)
        request.update(status='REJECTED', rejection_reason=reason.strip(), rejected_at=self.clock(), rejected_by=a['id'])
        return request

    def do_cancel_charge_request(self, s, a, p, db, rev):
        request = self.get(s, 'charge_requests', p.get('request_id'))
        self.own(request, a)
        require(request['status'] in ('PENDING', 'BOOKED'), 'INVALID_STATE', 'Request is no longer cancellable.')
        if request.get('right_id'):
            self.cancel_right(s, s['rights'][request['right_id']])
        request.update(status='CANCELLED', cancelled_at=self.clock())
        return request

    def do_scan_charge(self, s, a, p, db, rev):
        request = self.get(s, 'charge_requests', p.get('request_id'))
        self.own(request, a)
        token = p.get('qr_token')
        require(isinstance(token, str) and token.isascii() and 1 <= len(token) <= 128,
                'INVALID_QR', 'A valid charging confirmation code is required.', 400)
        require(request['status'] == 'BOOKED' and request.get('qr'), 'INVALID_STATE', 'Charging request is not confirmed.')
        require(hmac.compare_digest(token, request['qr']['token']), 'INVALID_QR', 'Charging code does not match.', 400)
        right = s['rights'][request['right_id']]
        require(request['arrival_time'] - 600 <= self.clock() <= request['qr']['expires_at'],
                'OUTSIDE_SCHEDULE', 'Charging check-in opens ten minutes before arrival and closes after its grace period.')
        return self.do_arrive(s, a, dict(right_id=right['id'], qr_token=right['qr']['token']), db, rev)

    def charging_qr(self, actor, request_id):
        # Authenticate through snapshot's standard boundary before reading tokens.
        self.snapshot(actor)
        with self.connect() as db:
            state = self.load(db)
        request = self.get(state, 'charge_requests', request_id)
        self.own(request, actor)
        require(request.get('qr'), 'QR_UNAVAILABLE', 'Charging QR is issued only after approval.', 404)
        right = state['rights'][request['right_id']]
        usable = request['status'] == 'BOOKED' and right['status'] == 'CONFIRMED' and request['arrival_time'] - 600 <= self.clock() <= request['qr']['expires_at']
        return dict(request_id=request['id'], right_id=right['id'], session_id=request['session_id'],
                    **request['qr'], status=right['status'] if request['status'] == 'BOOKED' else request['status'],
                    usable=usable, message='Request arrival; physical reception and charging still require evidence.' if usable else 'This code is not available for another arrival.',
                    svg=qr_svg(request['qr']['token']))

    def sync_charge_requests(self, state):
        for request in state['charge_requests'].values():
            if request['status'] not in ('BOOKED', 'CHARGING', 'START_PENDING', 'STOP_PENDING', 'INTERRUPTED'):
                continue
            right = state['rights'][request['right_id']]
            session = state['sessions'][request['session_id']]
            request.update(port_id=session['port_id'], spot_id=right['spot_id'],
                           scheduled_start=session['scheduled_start'], scheduled_end=session['scheduled_end'],
                           expected_collection_at=session['scheduled_end'], kw=session['kw'], duration=session['duration'])
            if right['status'] in ('CANCELLED', 'EXPIRED'):
                request['status'] = right['status']
            elif session['status'] in ('CANCELLED', 'EXPIRED', 'COMPLETED', 'CHARGING', 'START_PENDING', 'STOP_PENDING', 'BOOKED', 'INTERRUPTED'):
                request['status'] = session['status']
