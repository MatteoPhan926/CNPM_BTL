"""UC-D02/D03/D06, adapted from D_notComplete's redistribution controller and
simulation engine. The shared Service transaction owns stock, bays and receipts.
"""
from .shared import DomainError, POLICY, number, require


DISPATCHER = 'dispatcher'
ACTIVE_ORDERS = ('ISSUED', 'IN_PROGRESS')


def operator(actor):
    require(actor['role'] == 'operator', 'FORBIDDEN', 'Operator role required.', 403)


def vehicle_list(value):
    require(isinstance(value, list) and 1 <= len(value) <= 4 and
            all(isinstance(vid, str) and vid for vid in value) and
            len(set(value)) == len(value), 'INVALID_INPUT',
            'Choose one to four distinct vehicles.', 400)
    return value


class OperationsMixin:
    def _safe_transfer_spot(self, state, spot, now):
        return (self.fresh(spot, now) and spot['health'] == 'OPERABLE' and
                self.bay_ports_clear(state, spot['id'], now))

    def _transferable(self, state, vehicle, source, now):
        return (vehicle['hub_id'] == source and self.pickup_ready(state, vehicle, now, min_soc=0) and
                state['spots'][vehicle['spot_id']]['hub_id'] == source and
                not self.vehicle_claimed(state, vehicle['id']))

    def _reserve_transfer(self, state, fields):
        source, dest = fields['source_hub_id'], fields['dest_hub_id']
        self.get(state, 'hubs', source)
        self.get(state, 'hubs', dest)
        require(source != dest, 'INVALID_ROUTE', 'Choose two different hubs.', 400)
        staff = fields['staff_id']
        require(staff == DISPATCHER, 'INVALID_STAFF', 'Choose a dispatch employee.', 400)
        require(not any(o['status'] in ACTIVE_ORDERS and o['staff_id'] == staff
                        for o in state['orders'].values()),
                'STAFF_BUSY', 'The dispatcher already has an active order.')
        now = self.clock()
        charging = fields.get('charging_bays', False)
        require(type(charging) is bool, 'INVALID_INPUT', 'charging_bays must be boolean.', 400)
        rights = {}
        for vid in vehicle_list(fields['vehicle_ids']):
            vehicle = self.get(state, 'vehicles', vid)
            require(self._transferable(state, vehicle, source, now), 'VEHICLE_UNAVAILABLE',
                    f'{vid} is unavailable at the selected source hub.')
            right = self.allocate_right(state, 'operator', vehicle, dest, now, now + 3600,
                                        charging=charging)
            # A compatible charging bay prepares fleet placement. Role C owns
            # the later session and power reservation, after a verified arrival.
            right['created_by_charge'] = False
            # An issued transfer holds this bay until its own evidence is applied.
            right['status'] = 'HANDOVER_PENDING'
            rights[vid] = right['id']
        return rights

    def _draft_transfer(self, state, fields):
        # allocate_right adds new rights only. Use a private rights map to check
        # the whole truckload without reserving inventory during preview.
        self._reserve_transfer(dict(state, rights=state['rights'].copy()), fields)
        return self.new(state, 'orders', **fields, status='DRAFT', delivered=[], pending=[],
                        rights={}, created_at=self.clock())

    def do_transfer_preview(self, state, actor, payload, db, rev):
        operator(actor)
        fields = {k: payload.get(k) for k in ('source_hub_id', 'dest_hub_id', 'vehicle_ids', 'staff_id')}
        fields['charging_bays'] = payload.get('charging_bays', False)
        return self._draft_transfer(state, fields)

    def do_transfer_issue(self, state, actor, payload, db, rev):
        operator(actor)
        order = self.get(state, 'orders', payload.get('order_id'))
        require(order['status'] == 'DRAFT', 'INVALID_STATE', 'Review a draft order first.')
        rights = self._reserve_transfer(state, order)
        for vid, right_id in rights.items():
            state['rights'][right_id]['transfer_order_id'] = order['id']
            state['vehicles'][vid]['transfer_order_id'] = order['id']
        order.update(rights=rights, status='ISSUED', issued_at=self.clock())
        return order

    def _assigned_order(self, state, actor, payload):
        require(actor['role'] == 'dispatcher', 'FORBIDDEN', 'Dispatcher role required.', 403)
        order = self.get(state, 'orders', payload.get('order_id'))
        require(order['staff_id'] == actor['id'], 'FORBIDDEN',
                'This order is assigned to another dispatcher.', 403)
        return order

    def do_transfer_start(self, state, actor, payload, db, rev):
        order = self._assigned_order(state, actor, payload)
        require(order['status'] == 'ISSUED', 'INVALID_STATE', 'Only an issued order can start.')
        order.update(status='IN_PROGRESS', started_at=self.clock())
        return order

    def _check_handover(self, state, order, vid):
        vehicle = state['vehicles'][vid]
        right = state['rights'][order['rights'][vid]]
        source = state['spots'].get(vehicle['spot_id'])
        dest = state['spots'][right['spot_id']]
        now = self.clock()
        require(right.get('transfer_order_id') == order['id'] and
                right['status'] == 'HANDOVER_PENDING' and
                vehicle.get('transfer_order_id') == order['id'],
                'CLAIM_MISMATCH', 'Transfer claims no longer match this order.')
        require(vehicle['health'] == 'OPERABLE' and self.fresh(vehicle, now) and
                vehicle['hub_id'] == order['source_hub_id'] and source and
                source['state'] == 'OCCUPIED' and source['vehicle_id'] == vid and
                self._safe_transfer_spot(state, source, now) and not self.charge_blocked(state, vid),
                'TRANSFER_BLOCKED', 'Vehicle or departure spot requires reconciliation.')
        require(state['hubs'][right['hub_id']]['open'] and dest['state'] == 'EMPTY' and
                self._safe_transfer_spot(state, dest, now),
                'RECEPTION_BLOCKED', 'The committed destination bay cannot receive this vehicle.')
        return right

    def do_transfer_handover(self, state, actor, payload, db, rev):
        order = self._assigned_order(state, actor, payload)
        require(order['status'] == 'IN_PROGRESS', 'INVALID_STATE', 'Start the order first.')
        selected = vehicle_list(payload.get('vehicle_ids'))
        for vid in selected:
            require(vid in order['vehicle_ids'] and vid not in order['delivered'] and
                    vid not in order['pending'], 'INVALID_HANDOVER',
                    'Choose an outstanding vehicle without a pending acknowledgement.')
            right = self._check_handover(state, order, vid)
            # A separate command for each vehicle permits independently evidenced deliveries.
            self.request(state, 'TRANSFER', right, actor['id'], vehicle_id=vid,
                         order_id=order['id'], source_spot_id=state['vehicles'][vid]['spot_id'],
                         spot_id=right['spot_id'])
            order['pending'].append(vid)
        return dict(status='PENDING', order_id=order['id'], vehicle_ids=selected)

    def apply_transfer(self, state, command, observed):
        order = state['orders'][command['order_id']]
        vid = command['vehicle_id']
        require(order['status'] == 'IN_PROGRESS' and vid in order['pending'],
                'INVALID_STATE', 'Transfer handover is no longer pending.')
        right = self._check_handover(state, order, vid)
        require(command['source_spot_id'] == state['vehicles'][vid]['spot_id'] and
                command['spot_id'] == right['spot_id'] and command['record_id'] == right['id'],
                'POSITION_MISMATCH', 'Transfer evidence must match both recorded bays.')
        self.departure_effect(state, vid, command['source_spot_id'], observed)
        self.arrival_effect(state, right, observed)
        del state['vehicles'][vid]['transfer_order_id']
        order['pending'].remove(vid)
        order['delivered'].append(vid)
        if len(order['delivered']) == len(order['vehicle_ids']):
            order.update(status='COMPLETED', completed_at=self.clock())

    def reject_transfer(self, state, command):
        # A definitive rejected handover permits a new attempt. Ambiguous evidence
        # keeps the old command pending in Service and never enters this method.
        state['orders'][command['order_id']]['pending'].remove(command['vehicle_id'])

    def do_what_if(self, state, actor, payload, db, rev):
        operator(actor)
        target = self.get(state, 'hubs', payload.get('hub_id'))['id']
        factor = number(payload.get('demand_factor'), 'demand_factor', 0.5, 3.0)
        now = self.clock()
        # One-minute horizon. Count distinct fresh inbound vehicle reports, or
        # use the submitted D engine's configurable-demand baseline of three.
        inbound = sum(1 for vehicle in state['vehicles'].values()
                      if (report := vehicle.get('last_telemetry')) and
                      report.get('destinationHubId') == target and
                      0 <= now - report['observed_at'] <= 60)
        baseline = inbound or 3
        impact = []
        capacities = {}
        for hub in state['hubs'].values():
            cap = self.capacity(state, hub['id'], now, now + 1)
            capacities[hub['id']] = cap
            used = cap['capacity'] - cap['available']
            projected = used + (int(baseline * factor) if hub['id'] == target else 0)
            percent = round(100 * min(projected, cap['capacity']) / cap['capacity'], 1) if cap['capacity'] else 100
            impact.append(dict(hub_id=hub['id'], current_percent=cap['effective_percent'],
                               projected_percent=percent))
        recommendations = []
        for hub in impact:
            if hub['projected_percent'] < POLICY['ordinary_capacity'] * 100:
                continue
            source = hub['hub_id']
            candidates = [v for v in state['vehicles'].values() if self._transferable(state, v, source, now)]
            # Prefer the most spare capacity. Check the same bay and policy
            # constraints used at actual issue, including future reservations.
            for dest in sorted(capacities, key=lambda h: (-capacities[h]['available'], h)):
                if dest == source or not state['hubs'][dest]['open']:
                    continue
                scratch = dict(state, rights=state['rights'].copy())
                selected = []
                for vehicle in candidates:
                    try:
                        self.allocate_right(scratch, 'operator', vehicle, dest, now, now + 3600)
                    except DomainError:
                        continue
                    selected.append(vehicle['id'])
                    if len(selected) == 3:
                        break
                if selected:
                    recommendations.append(dict(source_hub_id=source, dest_hub_id=dest, vehicle_ids=selected))
                    break
        return self.new(state, 'scenarios', hub_id=target, demand_factor=factor, impact=impact,
                        base_revision=rev, created_at=now, baseline_vehicles=baseline,
                        baseline_source='RECENT_TELEMETRY' if inbound else 'SCENARIO_DEFAULT',
                        recommendations=recommendations)

    def do_what_if_draft(self, state, actor, payload, db, rev):
        operator(actor)
        scenario = self.get(state, 'scenarios', payload.get('scenario_id'))
        index = payload.get('recommendation_index')
        require(type(index) is int and 0 <= index < len(scenario['recommendations']),
                'INVALID_RECOMMENDATION', 'Select a recommendation from this simulation.', 400)
        fields = dict(scenario['recommendations'][index], staff_id=DISPATCHER, scenario_id=scenario['id'])
        return self._draft_transfer(state, fields)
