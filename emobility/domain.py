"""Transactional A/B/C/D application, with an explicitly opt-in test evidence adapter.

All domain documents participate in one SQLite transaction. Receipt and event
identities are separate: an intent retries a request; an event applies evidence.
No transaction remains open while a device/handover acknowledgement is pending.
"""
from __future__ import annotations

import copy
import hmac
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .active_services import active_service_count
from .charging_requests import ChargingRequestsMixin
from .iot_workflow import IotWorkflowMixin
from .monitoring import MonitoringMixin
from .operations import OperationsMixin
from .parking_qr import checkin_window_open, issue_parking_qr, qr_details
from .rental_qr import issue_rental_qr, rental_qr_details
from .shared import DomainError, LIVE_RIGHT, LIVE_SESSION, POLICY, fingerprint, number, overlap, require

ACTOR_ROLES = {'alice': 'student', 'bob': 'student', 'operator': 'operator',
               'dispatcher': 'dispatcher', 'technician': 'technician'}
COLLECTIONS = ('hubs', 'spots', 'ports', 'vehicles', 'holds', 'trips', 'rights',
               'visits', 'sessions', 'commands', 'incidents', 'plans', 'audit',
               'orders', 'scenarios', 'charge_requests')


def authenticate_actor(actor):
    actor_id = actor.get('id') if isinstance(actor, dict) else None
    require(isinstance(actor_id, str) and actor_id in ACTOR_ROLES
            and actor.get('role') == ACTOR_ROLES[actor_id],
            'UNAUTHORIZED', 'Authenticated application actor required.', 401)


class Service(IotWorkflowMixin, ChargingRequestsMixin, OperationsMixin, MonitoringMixin):
    def __init__(self, db_path, simulator=False, clock=None):
        self.db_path, self.simulator = str(db_path), simulator
        self.clock = clock or time.time
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS documents(kind TEXT, id TEXT, body TEXT NOT NULL,
                    PRIMARY KEY(kind,id));
                CREATE TABLE IF NOT EXISTS meta(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER);
                CREATE TABLE IF NOT EXISTS receipts(actor TEXT, intent TEXT, fingerprint TEXT,
                    response TEXT, error INTEGER, PRIMARY KEY(actor,intent));
                CREATE TABLE IF NOT EXISTS events(source TEXT, id TEXT, fingerprint TEXT,
                    body TEXT, result TEXT, PRIMARY KEY(source,id));
            ''')
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM meta').fetchone():
                db.execute('INSERT INTO meta VALUES(1,0)')
                self.save(db, self.seed())
            # Additive migration: preserve existing reservations and receipts.
            # BEGIN IMMEDIATE also prevents competing startups issuing two codes.
            migrated = False
            for rid, body in db.execute("SELECT id,body FROM documents WHERE kind='rights'").fetchall():
                right = json.loads(body)
                if 'qr' not in right and right['status'] in ('CONFIRMED', 'HANDOVER_PENDING', 'OFFERED'):
                    right['qr'] = issue_parking_qr(right, self.clock())
                    db.execute("UPDATE documents SET body=? WHERE kind='rights' AND id=?",
                               (json.dumps(right), rid))
                    migrated = True
            for hid, body in db.execute("SELECT id,body FROM documents WHERE kind='holds'").fetchall():
                hold = json.loads(body)
                if 'qr' not in hold and hold['status'] in ('ACTIVE', 'HANDOVER_PENDING'):
                    vehicle_body = db.execute("SELECT body FROM documents WHERE kind='vehicles' AND id=?",
                                              (hold['vehicle_id'],)).fetchone()
                    if vehicle_body:
                        hold['pickup_hub_id'] = json.loads(vehicle_body[0]).get('hub_id')
                    hold['qr'] = issue_rental_qr(hold, self.clock())
                    db.execute("UPDATE documents SET body=? WHERE kind='holds' AND id=?",
                               (json.dumps(hold), hid))
                    migrated = True
            if migrated:
                db.execute('UPDATE meta SET revision=revision+1')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=20)
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def seed(self):
        s = {k: {} for k in COLLECTIONS}
        observed = self.clock() if self.simulator else None
        for i, name in enumerate(('Metro Gateway', 'University Campus', 'Dormitory'), 1):
            h = f'H{i}'
            s['hubs'][h] = dict(id=h, name=name, power_kw=7.4, open=True)
            for j in range(1, 11):
                sid = f'{h}-S{j}'
                s['spots'][sid] = dict(id=sid, hub_id=h, state='EMPTY', vehicle_id=None,
                    health='OPERABLE', observed_at=observed, sequence=0, evidence='SIMULATED' if self.simulator else 'UNKNOWN')
                if j <= 2:
                    pid = f'{h}-C{j}'
                    s['ports'][pid] = dict(id=pid, spot_id=sid, hub_id=h, connector='TYPE2',
                        kw=3.7, plug='UNPLUGGED', power='OFF', health='OPERABLE', vehicle_id=None,
                        observed_at=observed, sequence=0, evidence='SIMULATED' if self.simulator else 'UNKNOWN')
        for vid, owner, hub, spot, soc in [('V1', None, 'H1', 'H1-S3', 75),
                ('V2', None, 'H2', 'H2-S3', 45), ('V3', None, 'H1', 'H1-S1', 68), ('P1', 'alice', None, None, 30),
                ('P2', 'bob', None, None, 40)]:
            s['vehicles'][vid] = dict(id=vid, label=vid, owner_id=owner,
                kind='personal' if owner else 'shared', hub_id=hub, spot_id=spot,
                soc=soc, battery_kwh=2.0, connector='TYPE2', health='OPERABLE',
                observed_at=observed, sequence=0, evidence='SIMULATED' if self.simulator else 'UNKNOWN')
            if spot:
                s['spots'][spot].update(state='OCCUPIED', vehicle_id=vid)
                s['visits']['seed-'+vid] = dict(id='seed-'+vid, owner_id='operator',
                    vehicle_id=vid, spot_id=spot, right_id=None, status='PARKED', arrived_at=self.clock())
        return s

    def load(self, db, *, include_audit=True):
        s = {k: {} for k in COLLECTIONS}
        query = 'SELECT kind,id,body FROM documents'
        if not include_audit:
            # Commands and timers append audit entries. Only snapshots need history.
            query += " WHERE kind <> 'audit'"
        for kind, rid, body in db.execute(query):
            s[kind][rid] = json.loads(body)
        return s

    def save(self, db, s):
        # Documents never disappear: cancellation and expiry are retained states.
        db.executemany('''
            INSERT INTO documents(kind, id, body) VALUES (?, ?, ?)
            ON CONFLICT(kind, id) DO UPDATE SET body = excluded.body
            WHERE documents.body <> excluded.body
        ''', (
            (kind, rid, json.dumps(row, allow_nan=False))
            for kind in COLLECTIONS for rid, row in s[kind].items()
        ))

    def new(self, s, collection, **fields):
        row = dict(id=uuid.uuid4().hex[:16], **fields)
        s[collection][row['id']] = row
        return row

    def get(self, s, kind, rid):
        require(isinstance(rid, str) and rid in s[kind], 'NOT_FOUND', f'{kind} record not found.', 404)
        return s[kind][rid]

    def own(self, row, actor, operator=False):
        require(row.get('owner_id') == actor['id'] or (operator and actor['role'] == 'operator'),
                'FORBIDDEN', 'This record belongs to another user.', 403)

    def fresh(self, row, now):
        t = row.get('observed_at')
        return t is not None and -5 <= now-t <= POLICY['freshness']

    def log(self, s, actor, action, before=None, after=None):
        self.new(s, 'audit', actor_id=actor, action=action, at=self.clock(), before=copy.deepcopy(before), after=copy.deepcopy(after))

    def incident(self, s, owner, record, message, key=None):
        if key:
            found = next((i for i in s['incidents'].values() if i.get('key') == key and i['status'] != 'RESOLVED'), None)
            if found:
                return found
        return self.new(s, 'incidents', owner_id=owner, record_id=record, message=message,
                        status='OPEN', response='', key=key, created_at=self.clock(), dependency='ROLE_D')

    def command(self, actor, action, payload, intent_id):
        authenticate_actor(actor)
        require(isinstance(payload, dict) and isinstance(action, str), 'INVALID_INPUT', 'Action and object payload required.', 400)
        require(isinstance(intent_id, str) and 1 <= len(intent_id) <= 128, 'INVALID_INTENT', 'An intent ID (1–128 characters) is required.', 400)
        try:
            fp = fingerprint([action, payload])
        except (ValueError, TypeError):
            raise DomainError('INVALID_INPUT', 'Payload must be finite JSON.', 400)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            receipt = db.execute('SELECT fingerprint,response,error FROM receipts WHERE actor=? AND intent=?', (actor['id'],intent_id)).fetchone()
            if receipt:
                require(receipt[0] == fp, 'INTENT_CONFLICT', 'This intent ID was already used with a different request.')
                result = json.loads(receipt[1])
                if receipt[2]:
                    raise DomainError(**result)
                return result
            s = self.load(db, include_audit=False)
            self.expire(s)
            baseline = copy.deepcopy(s)
            revision = db.execute('SELECT revision FROM meta').fetchone()[0]
            error = None
            try:
                handler = getattr(self, 'do_'+action, None)
                require(handler is not None, 'UNKNOWN_ACTION', 'Unknown command.', 400)
                if actor['role'] == 'dispatcher':
                    require(action in ('transfer_start', 'transfer_handover'), 'FORBIDDEN', 'Dispatcher action required.', 403)
                elif actor['role'] == 'technician':
                    require(action == 'd_update_incident', 'FORBIDDEN', 'Technician action required.', 403)
                if action.startswith('sim') or action in ('capacity_plan','schedule_preview','schedule_confirm','fleet_charge'):
                    require(actor['role'] == 'operator', 'FORBIDDEN', 'Operator role required.', 403)
                result = handler(s, actor, payload, db, revision)
                self.advance_iot_charging(s)
                self.sync_charge_requests(s)
                changes = [(kind,rid,baseline[kind].get(rid),row) for kind in COLLECTIONS if kind!='audit'
                           for rid,row in s[kind].items() if baseline[kind].get(rid)!=row]
                self.log(s, actor['id'], action,
                         [{ 'kind':k,'id':i,'value':b} for k,i,b,n in changes],
                         [{ 'kind':k,'id':i,'value':n} for k,i,b,n in changes])
                result = dict(status='CONFIRMED', code='OK', record=result, revision=revision+1)
                if isinstance(result['record'], dict) and result['record'].get('status') in ('HANDOVER_PENDING','START_PENDING','STOP_PENDING','PENDING','ASSISTANCE_PENDING'):
                    result['status'] = 'PENDING_VERIFICATION'
            except DomainError as exc:
                s = baseline
                error = exc
                result = dict(code=exc.code, message=exc.message, status=exc.status)
            self.save(db, s)
            db.execute('UPDATE meta SET revision=revision+1')
            db.execute('INSERT INTO receipts VALUES(?,?,?,?,?)', (actor['id'],intent_id,fp,json.dumps(result),bool(error)))
        if error:
            raise error
        return result

    def tick(self, *, refresh_simulated=False):
        if refresh_simulated:
            self.sim_guard()

        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            s = self.load(db, include_audit=False)
            before = fingerprint(s)

            if refresh_simulated:
                now = self.clock()

                for kind in ('spots', 'ports', 'vehicles'):
                    for row in s[kind].values():
                        observed = row.get('observed_at')

                        if (
                            row.get('evidence') != 'SIMULATED'
                            or (
                                observed is not None
                                and observed >= now
                            )
                        ):
                            continue

                        row.update(
                            observed_at=now,
                            sequence=row.get('sequence', 0) + 1
                        )

            self.expire(s)

            if fingerprint(s) != before:
                self.save(db, s)
                db.execute(
                    'UPDATE meta SET revision=revision+1'
                )

    def snapshot(self, actor):
        authenticate_actor(actor)
        self.tick()
        with self.connect() as db:
            db.execute('BEGIN')
            s = self.load(db)
            revision = db.execute('SELECT revision FROM meta').fetchone()[0]
        now = self.clock()
        for h in s['hubs'].values():
            h.update(self.capacity(s,h['id'],now,now+1))
        for k in ('spots','ports','vehicles'):
            for r in s[k].values():
                r['freshness'] = 'FRESH' if self.fresh(r,now) else ('UNKNOWN' if r['observed_at'] is None else 'STALE')
        for v in s['vehicles'].values():
            v['available'] = self.rentable(s,v,now)
            if actor['role'] == 'operator':
                v['transferable'] = bool(self._transferable(s, v, v['hub_id'], now))
        role, actor_id = actor['role'], actor['id']
        active_services = active_service_count(s, actor_id)
        if role != 'operator':
            for kind in ('holds', 'trips', 'rights', 'visits', 'sessions', 'commands', 'charge_requests'):
                s[kind] = {k: v for k, v in s[kind].items() if v['owner_id'] == actor_id}
            s['incidents'] = {
                k: v for k, v in s['incidents'].items()
                if v.get('owner_id') == actor_id or (role == 'technician' and v.get('technician_id') == actor_id)
            }
            s['orders'] = {k: v for k, v in s['orders'].items()
                           if role == 'dispatcher' and v['staff_id'] == actor_id and v['status'] != 'DRAFT'}
            s['plans'] = {}
            s['scenarios'] = {}
            s['vehicles'] = {k: v for k, v in s['vehicles'].items()
                             if v['owner_id'] in (None, actor_id)}
            for v in s['vehicles'].values():
                v.pop('last_telemetry', None)
                if v.get('transfer_order_id') not in s['orders']:
                    v.pop('transfer_order_id', None)
            for kind in ('spots', 'ports'):
                for row in s[kind].values():
                    if row.get('vehicle_id') not in s['vehicles']:
                        row['vehicle_id'] = None
            for kind in ('vehicles', 'spots', 'ports'):
                for row in s[kind].values():
                    if row.get('maintenance_ticket_id') not in s['incidents']:
                        row.pop('maintenance_ticket_id', None)
            s['audit'] = {k: dict(id=v['id'], actor_id=v['actor_id'], action=v['action'], at=v['at'])
                          for k, v in s['audit'].items() if v['actor_id'] == actor_id}
        return dict(actor=actor, revision=revision, now=now, simulator=self.simulator,
                    policy=POLICY, active_services=active_services,
                    **{k:list(v.values()) for k,v in s.items()})

    def right_blocks(self, right, start, end):
        # The bay remains claimed until a pending physical handover is reconciled,
        # even when another booking starts after its planned departure.
        return right['status'] == 'HANDOVER_PENDING' or (
            right['status'] in LIVE_RIGHT and overlap(start, end, right['start'], right['block_end'])
        )

    def bay_ports_clear(self, state, spot_id, now):
        return all(port['health'] == 'OPERABLE' and self.fresh(port, now) and
                   port['plug'] == 'UNPLUGGED' and port['power'] == 'OFF'
                   for port in state['ports'].values() if port['spot_id'] == spot_id)

    def capacity(self,s,hub,start,end):
        spots = [p for p in s['spots'].values() if p['hub_id']==hub]
        occupied = {p['id'] for p in spots if p['state']=='OCCUPIED'}
        unknown = {p['id'] for p in spots if p['id'] not in occupied and (p['state']=='UNKNOWN' or not self.fresh(p,self.clock()) or p['health']!='OPERABLE'
                   or not self.bay_ports_clear(s,p['id'],self.clock()))}
        held = {r['spot_id'] for r in s['rights'].values() if r['hub_id']==hub and self.right_blocks(r,start,end)} - occupied - unknown
        c = len(spots)
        used = len(occupied|unknown|held)
        ratio = used/c if c else 1
        return dict(capacity=c, occupied=len(occupied), unknown=len(unknown), held=len(held),
                    available=max(0,c-used), effective_percent=round(100*ratio,1),
                    level='HIGH' if ratio>=POLICY['high'] else 'RESTRICTED' if ratio>=POLICY['ordinary_capacity'] else 'WARNING' if ratio>=POLICY['warning'] else 'NORMAL')

    def vehicle_claimed(self,s,vid):
        return bool(s['vehicles'][vid].get('transfer_order_id')) or any(h['vehicle_id']==vid and h['status'] in ('ACTIVE','HANDOVER_PENDING') for h in s['holds'].values()) or any(t['vehicle_id']==vid and t['status']!='CLOSED' for t in s['trips'].values())

    def charge_blocked(self,s,vid):
        return any(p.get('vehicle_id')==vid and (p['plug']!='UNPLUGGED' or p['power']!='OFF' or not self.fresh(p,self.clock())) for p in s['ports'].values()) or any(c['vehicle_id']==vid and c['status'] in LIVE_SESSION for c in s['sessions'].values())

    def pickup_ready(self, s, v, now, min_soc=POLICY['rental_soc']):
        spot = s['spots'].get(v.get('spot_id'))
        return bool(v['kind'] == 'shared' and v['health'] == 'OPERABLE'
                    and v['soc'] >= min_soc and self.fresh(v, now)
                    and spot and spot['health'] == 'OPERABLE' and self.fresh(spot, now)
                    and spot['state'] == 'OCCUPIED' and spot['vehicle_id'] == v['id']
                    and self.bay_ports_clear(s, spot['id'], now)
                    and s['hubs'][spot['hub_id']]['open'] and not v.get('transfer_order_id')
                    and not self.charge_blocked(s, v['id']))

    def rentable(self, s, v, now):
        return self.pickup_ready(s, v, now) and not self.vehicle_claimed(s, v['id'])

    def do_reserve_vehicle(self,s,a,p,db,rev):
        require(a['role']=='student','FORBIDDEN','Student role required.',403)
        require(not any(h['owner_id']==a['id'] and h['status'] in ('ACTIVE','HANDOVER_PENDING') for h in s['holds'].values())
                and not any(t['owner_id']==a['id'] and t['status']!='CLOSED' for t in s['trips'].values()),
                'ACTIVE_JOURNEY','You already have a hold or an unfinished journey.')
        v=self.get(s,'vehicles',p.get('vehicle_id'))
        require(self.rentable(s,v,self.clock()),'VEHICLE_UNAVAILABLE','Vehicle is claimed, stale, charging or unsuitable for rental.')
        hold = self.new(s,'holds',owner_id=a['id'],vehicle_id=v['id'],status='ACTIVE',created_at=self.clock(),expires_at=self.clock()+POLICY['hold_seconds'])
        hold['pickup_hub_id'] = v['hub_id']
        hold['qr'] = issue_rental_qr(hold, self.clock())
        return hold

    def cancel_right(self,s,r,status='CANCELLED'):
        require(r['status']=='CONFIRMED','PARKING_IN_USE','Only an unused, unambiguous parking right can be cancelled.')
        for c in s['sessions'].values():
            if c['right_id']==r['id'] and c['status'] in LIVE_SESSION:
                require(c['status']=='BOOKED' and not self.connected(s,c),'CHARGE_IN_USE','Charging is in use or awaiting evidence.')
                c['status']=status
        r['status']=status

    def do_cancel_hold(self,s,a,p,db,rev):
        h=self.get(s,'holds',p.get('hold_id')); self.own(h,a)
        require(h['status']=='ACTIVE','HANDOVER_PENDING','Only an active hold before handover can be cancelled.')
        for r in s['rights'].values():
            if r.get('hold_id')==h['id'] and r['status'] in LIVE_RIGHT:
                self.cancel_right(s,r)
        h['status']='CANCELLED'
        return h

    def request(self,s,kind,row,owner,**details):
        existing=next((c for c in s['commands'].values() if c['kind']==kind and c['record_id']==row['id'] and c['status']=='PENDING'),None)
        if existing: return existing
        return self.new(s,'commands',kind=kind,record_id=row['id'],owner_id=owner,status='PENDING',
                        created_at=self.clock(),evidence='SIMULATOR_REQUIRED' if self.simulator else 'DEVICE_EVIDENCE_REQUIRED',**details)

    def rental_qr(self, actor, hold_id):
        authenticate_actor(actor)
        self.tick()
        with self.connect() as db:
            s = self.load(db)
        hold = self.get(s, 'holds', hold_id)
        self.own(hold, actor)
        require('qr' in hold, 'QR_UNAVAILABLE', 'This hold has no pickup confirmation code.', 404)
        return rental_qr_details(hold, self.clock())

    def do_scan_rental(self, s, a, p, db, rev):
        token = p.get('qr_token')
        require(isinstance(token, str) and token.isascii() and 1 <= len(token) <= 128,
                'INVALID_QR', 'A valid rental pickup code is required.', 400)
        if p.get('hold_id'):
            hold = self.get(s, 'holds', p['hold_id'])
        else:
            hold = next((h for h in s['holds'].values()
                         if hmac.compare_digest(h.get('qr', {}).get('token', ''), token)), None)
            require(hold is not None, 'INVALID_QR', 'Rental pickup code is not recognized.', 400)
        self.own(hold, a)
        require(hmac.compare_digest(hold.get('qr', {}).get('token', ''), token),
                'INVALID_QR', 'Pickup code does not match this hold.', 400)
        return self.do_pickup(s, a, dict(hold_id=hold['id']), db, rev)

    def do_pickup(self,s,a,p,db,rev):
        h=self.get(s,'holds',p.get('hold_id')); self.own(h,a)
        if h['status']=='HANDOVER_PENDING': return h
        require(h['status']=='ACTIVE' and h['expires_at']>self.clock(),'HOLD_EXPIRED','Hold is not active.')
        v=self.get(s,'vehicles',h['vehicle_id'])
        require(self.pickup_ready(s,v,self.clock()), 'VEHICLE_UNAVAILABLE','Pickup prerequisites no longer hold.')
        h['status']='HANDOVER_PENDING'
        self.request(s,'PICKUP',h,a['id'],vehicle_id=v['id'],spot_id=v['spot_id'])
        return h

    def authorized_vehicle(self,s,a,vid):
        v=self.get(s,'vehicles',vid)
        if v['kind']=='personal': self.own(v,a)
        else:
            require(any(h['owner_id']==a['id'] and h['vehicle_id']==vid and h['status'] in ('ACTIVE','HANDOVER_PENDING') for h in s['holds'].values())
                or any(t['owner_id']==a['id'] and t['vehicle_id']==vid and t['status']!='CLOSED' for t in s['trips'].values()),'FORBIDDEN','A current rental hold or journey is required.',403)
        return v

    def do_register_vehicle(self,s,a,p,db,rev):
        require(a['role']=='student','FORBIDDEN','Student role required.',403)
        label=p.get('label','').strip() if isinstance(p.get('label'),str) else ''
        require(1<=len(label)<=80,'INVALID_INPUT','Vehicle label required (max 80).',400)
        require(p.get('connector') in ('TYPE2','SCHUKO'),'INVALID_INPUT','Supported connector: TYPE2 or SCHUKO.',400)
        return self.new(s,'vehicles',owner_id=a['id'],kind='personal',label=label,
            battery_kwh=number(p.get('battery_kwh'),'Battery kWh',.1,150),soc=number(p.get('soc'),'SOC',0,100),
            connector=p['connector'],health='OPERABLE',hub_id=None,spot_id=None,observed_at=None,sequence=0,evidence='USER_DECLARED')

    def allocate_right(self,s,owner,v,hub,start,end,charging=False,spot_id=None,hold_id=None,recovery=False):
        now=self.clock(); h=self.get(s,'hubs',hub)
        require(h['open'],'HUB_CLOSED','Hub is closed to new allocations.')
        require(now-60<=start<=now+POLICY['max_advance'],'INVALID_WINDOW','Parking must start now or within 24 hours.',400)
        if v['kind']=='personal':
            require(POLICY['min_parking']<=end-start<=POLICY['max_parking'],'INVALID_WINDOW','Personal parking must last 15 minutes to 12 hours.',400)
        else: require(end>start,'INVALID_WINDOW','End must follow arrival.',400)
        block_end = end+POLICY['parking_buffer'] if v['kind']=='personal' else 10**12
        for r in s['rights'].values():
            if r['vehicle_id']==v['id'] and r['status'] in LIVE_RIGHT:
                require(not self.right_blocks(r,start,block_end),'VEHICLE_PARKING_CONFLICT','Vehicle already has an overlapping parking right.')
        cap=self.capacity(s,hub,start,block_end)
        require(cap['available']>0 and (recovery or cap['capacity']-cap['available']+1<=cap['capacity']*POLICY['ordinary_capacity']),
                'HUB_CAPACITY','No ordinary reception capacity; request operator assistance.')
        candidates=[]
        for spot in s['spots'].values():
            if spot['hub_id']!=hub or (spot_id and spot['id']!=spot_id): continue
            if spot['state']!='EMPTY' or spot['health']!='OPERABLE' or not self.fresh(spot,now): continue
            if any(r['spot_id']==spot['id'] and self.right_blocks(r,start,block_end) for r in s['rights'].values()): continue
            ports=[x for x in s['ports'].values() if x['spot_id']==spot['id']]
            if not self.bay_ports_clear(s, spot['id'], now): continue
            if charging and not any(x['connector']==v['connector'] for x in ports): continue
            candidates.append(spot)
        require(candidates,'NO_SPOT','No fresh, empty compatible spot is available.')
        # Charging bays remain selectable explicitly for independent-right reuse.
        candidates.sort(key=lambda x:(0 if charging else any(q['spot_id']==x['id'] for q in s['ports'].values()),x['id']))
        right = self.new(s,'rights',owner_id=owner,vehicle_id=v['id'],hub_id=hub,spot_id=candidates[0]['id'],
                        start=start,end=end,block_end=block_end,status='CONFIRMED',hold_id=hold_id,
                        created_by_charge=charging,recovery=recovery,created_at=now)
        right['qr'] = issue_parking_qr(right, now)
        right['reservation_type'] = 'PARKING_AND_CHARGING' if charging else 'PARKING_ONLY'
        return right

    def do_reserve_parking(self,s,a,p,db,rev):
        v=self.authorized_vehicle(s,a,p.get('vehicle_id'))
        hold_id=p.get('hold_id')
        if hold_id:
            h=self.get(s,'holds',hold_id); self.own(h,a)
            require(h['vehicle_id']==v['id'] and h['status'] in ('ACTIVE','HANDOVER_PENDING'),'INVALID_HOLD','Hold must match the current vehicle.')
        require(type(p.get('charging',False)) is bool,'INVALID_INPUT','charging must be boolean.',400)
        r=self.allocate_right(s,a['id'],v,p.get('hub_id'),number(p.get('start'),'start'),number(p.get('end'),'end'),p.get('charging',False),p.get('spot_id'),hold_id)
        if p.get('charging'):
            self.create_charge(s,a,v,r,p.get('target_soc'))
        return r

    def do_cancel_parking(self,s,a,p,db,rev):
        r=self.get(s,'rights',p.get('right_id')); self.own(r,a)
        self.cancel_right(s,r)
        return r

    def reception(self,s,r):
        now=self.clock(); spot=s['spots'][r['spot_id']]
        require(r['status'] in ('CONFIRMED','HANDOVER_PENDING'),'INVALID_RIGHT','Parking right is not valid for arrival.')
        require(now<=r['start']+POLICY['no_show'],'LATE_ARRIVAL','Arrival grace period has elapsed.')
        require(s['hubs'][r['hub_id']]['open'] and spot['health']=='OPERABLE' and spot['state']=='EMPTY' and self.fresh(spot,now),'RECEPTION_BLOCKED','Reception spot is occupied, closed or stale.')
        require(not any(x['id']!=r['id'] and x['spot_id']==r['spot_id'] and self.right_blocks(x,now,r['block_end']) for x in s['rights'].values()),'EARLY_CONFLICT','Early arrival conflicts with another right.')

    def do_arrive(self,s,a,p,db,rev):
        token = p.get('qr_token')
        require(isinstance(token, str) and token.isascii() and 1 <= len(token) <= 128,
                'INVALID_QR', 'A valid parking confirmation code is required.', 400)
        if p.get('right_id'):
            r = self.get(s, 'rights', p['right_id'])
        else:
            r = next((r for r in s['rights'].values()
                      if hmac.compare_digest(r.get('qr', {}).get('token', ''), token)), None)
            require(r is not None, 'INVALID_QR', 'Parking confirmation code is not recognized.', 400)
        self.own(r,a)
        require(hmac.compare_digest(r.get('qr', {}).get('token', ''), token),
                'INVALID_QR', 'Confirmation code does not match this reservation.', 400)
        require(r['status'] in ('CONFIRMED', 'HANDOVER_PENDING'),
                'INVALID_RIGHT', 'Parking right is not valid for arrival.')
        require(s['vehicles'][r['vehicle_id']]['kind']=='personal','USE_RETURN','Shared vehicles must use return journey.')
        if r.get('charge_request_id'):
            require(checkin_window_open(r, self.clock()), 'OUTSIDE_SCHEDULE',
                    'Charging check-in opens ten minutes before arrival and closes after its grace period.')
        if r['status'] == 'HANDOVER_PENDING':
            return r
        require(not any(other['vehicle_id'] == r['vehicle_id'] and other['status'] == 'HANDOVER_PENDING'
                        for other in s['rights'].values()), 'ARRIVAL_PENDING',
                'Another arrival for this vehicle is awaiting reception evidence.')
        self.reception(s,r)
        require(not s['vehicles'][r['vehicle_id']].get('spot_id'),'ALREADY_PARKED','Vehicle is already parked.')
        r['status']='HANDOVER_PENDING'
        self.request(s,'ARRIVAL',r,a['id'],vehicle_id=r['vehicle_id'],spot_id=r['spot_id'])
        return r

    def parking_qr(self, actor, right_id):
        authenticate_actor(actor)
        self.tick()
        with self.connect() as db:
            s = self.load(db)
        right = self.get(s, 'rights', right_id)
        self.own(right, actor)
        require('qr' in right, 'QR_UNAVAILABLE', 'This record has no parking confirmation code.', 404)
        return qr_details(right, self.clock())

    def do_depart(self,s,a,p,db,rev):
        v=self.get(s,'visits',p.get('visit_id')); self.own(v,a)
        require(s['vehicles'][v['vehicle_id']]['kind']=='personal','USE_PICKUP','Shared vehicles must use rental pickup.')
        require(v['status'] in ('PARKED','HANDOVER_PENDING'),'NOT_PARKED','Visit already departed.')
        require(not self.charge_blocked(s,v['vehicle_id']),'CONNECTED','Finish/cancel charging and verify unplug before departure.')
        v['status']='HANDOVER_PENDING'
        self.request(s,'DEPARTURE',v,a['id'],vehicle_id=v['vehicle_id'],spot_id=v['spot_id'])
        return v

    def do_return_vehicle(self,s,a,p,db,rev):
        t=self.get(s,'trips',p.get('trip_id')); self.own(t,a)
        require(t['status']!='CLOSED','TRIP_CLOSED','Trip is already closed.')
        if t['status']=='HANDOVER_PENDING': return t
        v=s['vehicles'][t['vehicle_id']]
        try:
            if p.get('right_id'):
                r=self.get(s,'rights',p['right_id']); self.own(r,a)
                require(r['vehicle_id']==v['id'] and r['hub_id']==p.get('hub_id'),'RIGHT_MISMATCH','Parking right does not match destination/vehicle.')
            else:
                r=next((x for x in s['rights'].values() if x['vehicle_id']==v['id'] and x['owner_id']==a['id'] and x['hub_id']==p.get('hub_id') and x['status']=='CONFIRMED'),None)
                if not r: r=self.allocate_right(s,a['id'],v,p.get('hub_id'),self.clock(),self.clock()+3600)
            self.reception(s,r)
        except DomainError as e:
            if e.code not in ('HUB_CAPACITY','NO_SPOT','RECEPTION_BLOCKED','LATE_ARRIVAL','HUB_CLOSED','EARLY_CONFLICT'): raise
            t['status']='ASSISTANCE_PENDING'
            self.incident(s,a['id'],t['id'],f'Return assistance at {p.get("hub_id")}: {e.message}', 'return-'+t['id'])
            return t
        t.update(status='HANDOVER_PENDING',return_right_id=r['id'])
        r['status']='HANDOVER_PENDING'
        self.request(s,'RETURN',t,a['id'],vehicle_id=v['id'],spot_id=r['spot_id'],right_id=r['id'])
        return t

    def connected(self,s,c):
        port=s['ports'][c['port_id']]
        return port.get('vehicle_id')==c['vehicle_id'] and (port['plug']!='UNPLUGGED' or port['power']!='OFF') or any(x['record_id']==c['id'] and x['status']=='PENDING' for x in s['commands'].values())

    def check_charge_resources(self, s, vehicle_id, port):
        vehicle = s['vehicles'][vehicle_id]
        spot = s['spots'][port['spot_id']]
        require(all(row['health'] == 'OPERABLE' for row in (vehicle, spot, port)),
                'RESOURCE_UNAVAILABLE', 'Vehicle, parking bay and charging port must be operational.')
        require(not vehicle.get('transfer_order_id'), 'VEHICLE_CLAIMED', 'Vehicle is reserved for redistribution.')

    def create_charge(self,s,a,v,r,target,scheduled_start=None):
        require(v['kind']=='personal' or a['role']=='operator','FORBIDDEN','Only operators schedule fleet charging.',403)
        target=number(target,'Target SOC',0,100)
        require(target>v['soc'],'INVALID_TARGET','Target SOC must exceed current SOC.')
        ports=[p for p in s['ports'].values() if p['spot_id']==r['spot_id'] and p['connector']==v['connector']]
        require(ports,'NO_PORT','Parking spot has no compatible charging port.')
        port=ports[0]; now=self.clock()
        self.check_charge_resources(s, v['id'], port)
        require(port['health']=='OPERABLE' and self.fresh(port,now) and port['power']=='OFF'
            and (port['plug']=='UNPLUGGED' or port.get('vehicle_id')==v['id']),'PORT_UNAVAILABLE','Port is faulty, connected to another vehicle or stale.')
        require(not any(c['vehicle_id']==v['id'] and c['status'] in LIVE_SESSION and overlap(r['start'],r['end'],c['start'],c['end']) for c in s['sessions'].values()),'CHARGE_CONFLICT','Vehicle has an overlapping charging session.')
        require(not any(c['port_id']==port['id'] and c['status'] in LIVE_SESSION and overlap(r['start'],r['end'],c['start'],c['end']) for c in s['sessions'].values()),'PORT_CONFLICT','Port already reserved.')
        kw=min(port['kw'],s['hubs'][port['hub_id']]['power_kw'])
        require(kw>0,'NO_POWER','No power available at Hub.')
        duration=(target-v['soc'])/100*v['battery_kwh']/(kw*POLICY['efficiency'])*3600
        # A charging-only allocation shares one time boundary with its parking
        # right. Reading the wall clock again can otherwise add microseconds and
        # incorrectly reject an exactly sized parking window.
        start=max(now,r['start']) if scheduled_start is None else scheduled_start
        require(start>=r['start'],'INVALID_WINDOW','Charging cannot precede its parking right.')
        end=start+duration
        require(end<=r['end'],'INSUFFICIENT_TIME','Requested SOC cannot be reached within parking window.')
        require(self.power_fits(s,port['hub_id'],start,end,kw),'POWER_CONFLICT','Hub power already committed during this time.')
        return self.new(s,'sessions',owner_id=a['id'],vehicle_id=v['id'],right_id=r['id'],port_id=port['id'],
            reservation_type='PARKING_AND_CHARGING' if r.get('created_by_charge') else 'ADD_CHARGING',
            iot_managed=r.get('iot_managed',False),
            status='BOOKED',target_soc=target,start=start,end=r['end'],scheduled_start=start,scheduled_end=end,
            kw=kw,duration=duration,created_at=now,created_parking=r.get('created_by_charge',False))

    def power_fits(self,s,hub,start,end,kw,exclude=None,allocations=None):
        items=allocations if allocations is not None else [c for c in s['sessions'].values() if c['status'] in LIVE_SESSION and c['id']!=exclude and s['ports'][c['port_id']]['hub_id']==hub]
        points={start}
        for c in items:
            if overlap(start,end,c['scheduled_start'],c['scheduled_end']): points.add(max(start,c['scheduled_start']))
        return all(kw+sum(c['kw'] for c in items if c['scheduled_start']<=t<c['scheduled_end'])<=s['hubs'][hub]['power_kw']+.00001 for t in points)

    def do_register_charge(self,s,a,p,db,rev):
        r=self.get(s,'rights',p.get('right_id')); self.own(r,a)
        require(r['status'] in ('CONFIRMED','CONSUMED'),'INVALID_RIGHT','An active parking right is required.')
        if r['status'] == 'CONSUMED':
            require(any(visit['right_id'] == r['id'] and visit['status'] == 'PARKED'
                        for visit in s['visits'].values()),
                    'VISIT_ENDED', 'This parking visit has already ended or is departing.')
        v=self.authorized_vehicle(s,a,r['vehicle_id'])
        return self.create_charge(s,a,v,r,p.get('target_soc'))

    def session(self,s,a,p):
        c=self.get(s,'sessions',p.get('session_id')); self.own(c,a,operator=True)
        return c,s['ports'][c['port_id']]

    def do_plug(self,s,a,p,db,rev):
        c,port=self.session(s,a,p)
        self.check_charge_resources(s, c['vehicle_id'], port)
        require(c['status']=='BOOKED','INVALID_STATE','Only a booked session can prepare a connection.')
        require(c['start']-600<=self.clock()<c['end'],'OUTSIDE_SCHEDULE','Connection preparation opens ten minutes before the session.')
        require(s['vehicles'][c['vehicle_id']]['spot_id']==port['spot_id'],'NOT_PARKED','Vehicle must be verified at the charging spot.')
        require(port['plug']=='UNPLUGGED' and port['power']=='OFF' and port['health']=='OPERABLE' and self.fresh(port,self.clock()),'PORT_UNAVAILABLE','Port cannot accept a connection.')
        self.request(s,'PLUG',c,c['owner_id'],vehicle_id=c['vehicle_id'],port_id=port['id'],spot_id=port['spot_id'])
        return dict(c, status='PENDING')

    def port_command_pending(self, state, port, kind):
        return any(cmd.get('port_id') == port['id'] and cmd['kind'] == kind and cmd['status'] == 'PENDING'
                   for cmd in state['commands'].values())

    def do_start_charge(self,s,a,p,db,rev):
        c,port=self.session(s,a,p)
        self.check_charge_resources(s, c['vehicle_id'], port)
        if c['status']=='START_PENDING': return c
        require(not self.port_command_pending(s, port, 'UNPLUG'), 'UNPLUG_PENDING',
                'Wait for the outstanding disconnection before starting charging.')
        require(c['status']=='BOOKED','INVALID_STATE','Session must be booked.')
        require(c['scheduled_start']<=self.clock()<c['scheduled_end'],'OUTSIDE_SCHEDULE','Charging is outside its approved schedule.')
        running=sum(x['kw'] for x in s['sessions'].values() if x['status'] in ('START_PENDING','CHARGING','STOP_PENDING')
                    and x['id']!=c['id'] and s['ports'][x['port_id']]['hub_id']==port['hub_id'])
        require(running+c['kw']<=s['hubs'][port['hub_id']]['power_kw'],'POWER_CONFLICT','Hub power remains claimed until stop evidence arrives.')
        require(port['plug']=='CONNECTED' and port['vehicle_id']==c['vehicle_id'] and port['power']=='OFF'
            and port['health']=='OPERABLE' and self.fresh(port,self.clock()),'NOT_CONNECTED','Fresh verified connection and operational port required.')
        c['status']='START_PENDING'
        self.request(s,'START',c,c['owner_id'],port_id=port['id'],vehicle_id=c['vehicle_id'])
        return c

    def do_stop_charge(self,s,a,p,db,rev):
        c,port=self.session(s,a,p)
        require(c['status'] in ('CHARGING','START_PENDING','STOP_PENDING'),'INVALID_STATE','Session is not running or pending.')
        c['status']='STOP_PENDING'
        self.request(s,'STOP',c,c['owner_id'],port_id=port['id'],vehicle_id=c['vehicle_id'])
        return c

    def do_unplug(self,s,a,p,db,rev):
        c,port=self.session(s,a,p)
        require(not any(other['id'] != c['id'] and other['port_id'] == port['id'] and
                        other['status'] in ('START_PENDING', 'CHARGING', 'STOP_PENDING')
                        for other in s['sessions'].values()), 'PORT_IN_USE',
                'Another charging session controls this port.')
        require(c['status'] in ('COMPLETED','CANCELLED','INTERRUPTED','EXPIRED','BOOKED') and port['power']=='OFF'
            and port['plug']=='CONNECTED' and port['vehicle_id']==c['vehicle_id'] and self.fresh(port,self.clock()),'POWER_NOT_OFF','Verified power off and connection required before unplug.')
        self.request(s,'UNPLUG',c,c['owner_id'],port_id=port['id'],vehicle_id=c['vehicle_id'])
        return dict(c,status='PENDING')

    def do_cancel_charge(self,s,a,p,db,rev):
        c,port=self.session(s,a,p)
        require(c['status']=='BOOKED' and not self.connected(s,c),'CHARGE_IN_USE','Only an unused and disconnected booking can be cancelled.')
        c['status']='CANCELLED'
        r=s['rights'][c['right_id']]
        if c['created_parking'] and r['status']=='CONFIRMED': self.cancel_right(s,r)
        return c

    def do_support(self,s,a,p,db,rev):
        rid=p.get('record_id')
        row=next((s[k][rid] for k in ('holds','trips','rights','visits','sessions') if isinstance(rid,str) and rid in s[k]),None)
        require(row is not None,'NOT_FOUND','Select a journey, hold, parking right or charging session.',404)
        self.own(row,a)
        message=p.get('message')
        require(isinstance(message,str) and 1<=len(message.strip())<=2000,'INVALID_INPUT','Support message must contain 1–2000 characters.',400)
        return self.incident(s,a['id'],rid,message.strip(),'support-'+rid)

    def do_capacity_plan(self,s,a,p,db,rev):
        incident=self.get(s,'incidents',p.get('incident_id'))
        require(incident['status'] in ('OPEN','WAITING_FOR_D','DECLINED'),'INVALID_STATE','This incident already has an offer.')
        rid=incident['record_id']
        row=next((s[k][rid] for k in ('trips','rights') if rid in s[k]),None)
        require(row is not None,'INVALID_RECORD','Capacity recovery requires a trip or parking right.')
        require(row['status'] not in ('CLOSED','CONSUMED','CANCELLED','EXPIRED'),'INVALID_STATE','This record is no longer eligible for recovery.')
        reason=p.get('reason',incident['message'])
        require(isinstance(reason,str) and 3<=len(reason)<=2000,'INVALID_INPUT','A recovery reason is required.',400)
        v=s['vehicles'][row['vehicle_id']]
        # Supersede only after consent. Temporarily exclude the old right during
        # conflict checks, retaining its physical bay claim until accepted.
        old=row if rid in s['rights'] else None
        if old:
            require(old['status']=='CONFIRMED','HANDOVER_PENDING','Cannot redirect a pending arrival.')
            old['status']='REPLACEMENT_CHECK'
        try:
            right=self.allocate_right(s,incident['owner_id'],v,p.get('hub_id'),self.clock(),
                self.clock()+max(900,(old['end']-self.clock()) if old else 3600),recovery=True)
        finally:
            if old: old['status']='CONFIRMED'
        right['status']='OFFERED'
        right['replaces_right_id']=old['id'] if old else None
        incident.update(status='OFFERED',offered_right_id=right['id'],response=reason,
                        offer_expires_at=self.clock()+600)
        return incident

    def do_accept_capacity(self,s,a,p,db,rev):
        i=self.get(s,'incidents',p.get('incident_id')); self.own(i,a)
        require(type(p.get('accept')) is bool,'INVALID_INPUT','accept must be boolean.',400)
        require(i['status']=='OFFERED','NO_OFFER','No pending recovery offer.')
        r=s['rights'][i['offered_right_id']]
        require(r['status']=='OFFERED' and i['offer_expires_at']>=self.clock(),'OFFER_EXPIRED','Recovery offer expired.')
        if not p['accept']:
            r['status']='CANCELLED'; i['status']='DECLINED'; return i
        # Recheck at consent; never pretend the physical reception occurred.
        r['status']='CONFIRMED'
        self.reception(s,r)
        if r.get('replaces_right_id'):
            self.cancel_right(s,s['rights'][r['replaces_right_id']])
        i.update(status='WAITING_FOR_RECEPTION',response='Customer accepted; physical reception is still required.')
        return i

    def schedule_inputs(self, s):
        now = self.clock()

        inputs = {
            k: s[k]
            for k in (
                'hubs',
                'rights',
                'sessions',
                'holds',
                'trips'
            )
        }

        for kind in ('spots', 'ports', 'vehicles'):
            inputs[kind] = {
                rid: dict(
                    {
                        k: v
                        for k, v in row.items()
                        if k not in (
                            'observed_at',
                            'sequence'
                        )
                    },
                    freshness_ok=self.fresh(row, now)
                )
                for rid, row in s[kind].items()
            }

        return fingerprint(inputs)

    def build_schedule(self,s):
        allocations=[]; unmet=[]; now=self.clock()
        # Keep feasible commitments fixed. Proposals never move a vehicle/cable.
        sessions=sorted((c for c in s['sessions'].values() if c['status'] in LIVE_SESSION),
                        key=lambda c:(c['end'],s['vehicles'][c['vehicle_id']]['soc'],c['id']))
        for c in sessions:
            port=s['ports'][c['port_id']]; v=s['vehicles'][c['vehicle_id']]
            hub=port['hub_id']
            reason=None
            if any(row['health'] != 'OPERABLE' for row in (port, v, s['spots'][port['spot_id']])) or not self.fresh(port, now):
                reason='Vehicle, bay or port is unavailable; review the commitment with Role D.'
            elif c['end']<=now: reason='Deadline passed; stop/reconcile before reallocating.'
            elif c['status']=='BOOKED' and not self.power_fits(s,hub,c['scheduled_start'],c['scheduled_end'],c['kw'],allocations=[x for x in allocations if x['hub_id']==hub]): reason='Hub power limit cannot serve this commitment.'
            if reason:
                unmet.append(dict(session_id=c['id'],vehicle_id=v['id'],reason=reason))
            else:
                allocations.append(dict(session_id=c['id'],vehicle_id=v['id'],port_id=port['id'],hub_id=hub,
                    scheduled_start=c['scheduled_start'],scheduled_end=c['scheduled_end'],kw=c['kw'],
                    priority=len(allocations)+1,status=c['status'],preparation='READY' if self.connected(s,c) else 'WAITING_FOR_PHYSICAL_CONNECTION'))
        fleet=[]
        for v in s['vehicles'].values():
            if v['kind']=='shared' and v['soc']<80 and v['health']=='OPERABLE' and not self.vehicle_claimed(s,v['id']) and not self.charge_blocked(s,v['id']):
                fleet.append(dict(vehicle_id=v['id'],soc=v['soc'],target_soc=80,
                    energy_kwh=round((80-v['soc'])/100*v['battery_kwh'],3),
                    status='WAITING_FOR_PREPARATION',reason='Role D must position and connect vehicle; no physical action inferred.'))
        return allocations,unmet,sorted(fleet,key=lambda v:v['soc'])

    def do_schedule_preview(self,s,a,p,db,rev):
        allocations,unmet,fleet=self.build_schedule(s)
        return self.new(s,'plans',kind='CHARGING',status='DRAFT',created_at=self.clock(),
            expires_at=self.clock()+90,input_fingerprint=self.schedule_inputs(s),base_revision=rev,
            allocations=allocations,unmet=unmet,fleet_demand=fleet)

    def do_schedule_confirm(self,s,a,p,db,rev):
        plan=self.get(s,'plans',p.get('plan_id'))
        require(plan['status']=='DRAFT','INVALID_STATE','Plan is no longer a draft.')
        require(plan['expires_at']>=self.clock() and plan['input_fingerprint']==self.schedule_inputs(s),'STALE_PLAN','Resource state changed; generate a new plan.')
        allocations,unmet,fleet=self.build_schedule(s)
        require(not unmet,'UNMET_DEMAND','Plan has infeasible commitments; resolve them before approval.')
        for item in allocations:
            c=s['sessions'][item['session_id']]
            c.update(scheduled_start=item['scheduled_start'],scheduled_end=item['scheduled_end'],kw=item['kw'],plan_id=plan['id'])
        plan.update(status='APPLIED',approved_by=a['id'],approved_at=self.clock())
        return plan

    def do_fleet_charge(self,s,a,p,db,rev):
        v=self.get(s,'vehicles',p.get('vehicle_id'))
        require(v['kind']=='shared' and not self.vehicle_claimed(s,v['id']) and not self.charge_blocked(s,v['id']), 'VEHICLE_CLAIMED','Fleet vehicle is claimed or charging.')
        require(v['spot_id'] and any(x['spot_id']==v['spot_id'] for x in s['ports'].values()),'PREPARATION_REQUIRED','Role D must first place the fleet vehicle at a charging spot.')
        now=self.clock()
        r=self.new(s,'rights',owner_id=a['id'],vehicle_id=v['id'],hub_id=v['hub_id'],spot_id=v['spot_id'],
            start=now,end=now+43200,block_end=10**12,status='CONSUMED',hold_id=None,created_by_charge=True,recovery=False,created_at=now)
        return self.create_charge(s,a,v,r,p.get('target_soc',80))

    def sim_guard(self):
        require(self.simulator,'SIMULATOR_DISABLED','Synthetic evidence requires the local server to run with --simulator.',403)

    def do_sim_refresh(self,s,a,p,db,rev):
        self.sim_guard()
        for kind in ('spots','ports','vehicles'):
            for row in s[kind].values():
                row.update(observed_at=self.clock(),sequence=row['sequence']+1,evidence='SIMULATED')
        return dict(status='SIMULATED',message='Simulated observations renewed; this is not physical verification.')

    def do_sim_observe(self,s,a,p,db,rev):
        self.sim_guard()
        kind=p.get('resource_type')
        require(kind in ('spots','ports','vehicles'),'INVALID_INPUT','Unsupported simulated resource type.',400)
        row=self.get(s,kind,p.get('resource_id'))
        observed=number(p.get('observed_at',self.clock()),'observed_at')
        sequence=number(p.get('sequence',row['sequence']+1),'sequence',1,10**12)
        require(sequence.is_integer(),'INVALID_INPUT','sequence must be an integer.',400)
        require(self.clock()-POLICY['freshness']<=observed<=self.clock()+5 and observed>=(row.get('observed_at') or 0)
                and sequence>row['sequence'],'STALE_EVENT','Stale or out-of-order observation rejected.')
        if 'health' in p:
            require(p['health'] in ('OPERABLE','OUT_OF_SERVICE','INSPECTION_PENDING'),'INVALID_INPUT','Invalid health state.',400)
            require(p['health'] == row['health'] or
                    (not row.get('maintenance_ticket_id') and row['health'] != 'DEACTIVATED'),
                    'MAINTENANCE_LOCK', 'Resource health is managed by Role D.')
            row['health']=p['health']
        if 'soc' in p:
            require(kind=='vehicles','INVALID_INPUT','SOC belongs to vehicles.',400)
            row['soc']=number(p['soc'],'soc',0,100)
        if 'state' in p:
            require(kind=='spots' and p['state']=='UNKNOWN','INVALID_INPUT','Only UNKNOWN may be injected without a handover command.',400)
            row['state']='UNKNOWN'
        row.update(observed_at=observed,sequence=int(sequence),evidence='SIMULATED')
        if row['health']!='OPERABLE':
            self.incident(s,'operator',row['id'],'Simulated resource fault: isolate new allocation; Role D repair required.','fault-'+row['id'])
            if kind=='ports':
                for c in s['sessions'].values():
                    if c['port_id']==row['id'] and c['status'] in LIVE_SESSION:
                        self.incident(s,c['owner_id'],c['id'],'Charging commitment affected by port fault.','charge-fault-'+c['id'])
                        if c['status'] in ('CHARGING','START_PENDING'):
                            c['status']='STOP_PENDING'
                            self.request(s,'STOP',c,c['owner_id'],port_id=row['id'],vehicle_id=c['vehicle_id'])
        return row

    def do_simulate(self,s,a,p,db,rev):
        self.sim_guard()
        command=self.get(s,'commands',p.get('command_id'))
        event_id=p.get('event_id',uuid.uuid4().hex)
        require(isinstance(event_id,str) and 1<=len(event_id)<=128,'INVALID_INPUT','Event ID must contain 1–128 characters.',400)
        # Fingerprint the supplied event, not defaults computed at retry time.
        fp=fingerprint({k:v for k,v in p.items() if k!='event_id'})
        old=db.execute('SELECT fingerprint,result FROM events WHERE source=? AND id=?',('SIMULATOR',event_id)).fetchone()
        if old:
            require(old[0]==fp,'EVENT_CONFLICT','Event identity reused with different evidence.')
            return json.loads(old[1])
        observed=number(p.get('observed_at',self.clock()),'observed_at')
        require(self.clock()-POLICY['freshness']<=observed<=self.clock()+5 and observed>=command['created_at'],
                'STALE_EVENT','Acknowledgement is stale, future-dated or predates its command.')
        outcome=p.get('outcome','ACK')
        require(outcome in ('ACK','REJECT','UNKNOWN'),'INVALID_INPUT','Outcome must be ACK, REJECT or UNKNOWN.',400)
        result=dict(status='ALREADY_APPLIED',command_id=command['id'],evidence='SIMULATED')
        if command['status']=='PENDING':
            mismatch=any(k in p and p[k]!=command.get(k) for k in ('spot_id','source_spot_id','port_id','vehicle_id','order_id','right_id'))
            if mismatch:
                self.incident(s,command['owner_id'],command['record_id'],'Wrong-resource simulated evidence: manual reconciliation required.','mismatch-'+command['id'])
                result['status']='ANOMALY'
            elif outcome=='UNKNOWN':
                self.incident(s,command['owner_id'],command['record_id'],'Ambiguous outcome; pending claim retained.','pending-'+command['id'])
                result['status']='PENDING'
            else:
                # Effect validation can fail after a resource changes. Retain the
                # evidence and a reconciliation incident without half-applying it.
                before=copy.deepcopy(s)
                try:
                    if outcome=='ACK': self.apply_evidence(s,command,observed)
                    else: self.reject_evidence(s,command)
                    command.update(status='ACKNOWLEDGED' if outcome=='ACK' else 'REJECTED',event_id=event_id,observed_at=observed)
                    result['status']=command['status']
                except DomainError as exc:
                    s.clear(); s.update(before)
                    command=s['commands'][command['id']]
                    self.incident(s,command['owner_id'],command['record_id'],f'Unapplied evidence: {exc.message}','reconcile-'+command['id'])
                    result.update(status='ANOMALY',reason=exc.message)
        body=dict(p,source_id='SIMULATOR',event_id=event_id,observed_at=observed,received_at=self.clock(),verification='CONTROLLED_SIMULATOR_ONLY')
        db.execute('INSERT INTO events VALUES(?,?,?,?,?)',('SIMULATOR',event_id,fp,json.dumps(body),json.dumps(result)))
        return result

    def stamp(self,row,observed):
        require(observed>=(row.get('observed_at') or 0),'STALE_EVENT','Evidence would overwrite a newer resource observation.')
        row.update(observed_at=observed,sequence=row.get('sequence',0)+1,evidence='SIMULATED')

    def departure_effect(self,s,vid,spotid,observed):
        v=s['vehicles'][vid]; spot=s['spots'][spotid]
        require(spot['vehicle_id']==vid and spot['state']=='OCCUPIED' and v['spot_id']==spotid,'POSITION_MISMATCH','Vehicle position does not match departure.')
        require(not self.charge_blocked(s,vid),'CONNECTED','Vehicle has an unresolved charging commitment or connection.')
        self.stamp(spot,observed); self.stamp(v,observed)
        spot.update(state='EMPTY',vehicle_id=None)
        v.update(hub_id=None,spot_id=None)
        for visit in s['visits'].values():
            if visit['vehicle_id']==vid and visit['status'] in ('PARKED','HANDOVER_PENDING'):
                visit.update(status='DEPARTED',departed_at=self.clock())

    def arrival_effect(self,s,r,observed):
        spot=s['spots'][r['spot_id']]; v=s['vehicles'][r['vehicle_id']]
        # Pending evidence may arrive after the grace deadline: pending claims
        # never expire. Evaluate reception rather than discarding valid evidence.
        require(r['status']=='HANDOVER_PENDING' and spot['state']=='EMPTY' and spot['health']=='OPERABLE'
                and s['hubs'][r['hub_id']]['open'] and not v['spot_id'],'RECEPTION_BLOCKED','Reception no longer matches an empty authorized spot.')
        self.stamp(spot,observed); self.stamp(v,observed)
        spot.update(state='OCCUPIED',vehicle_id=v['id'])
        v.update(hub_id=r['hub_id'],spot_id=r['spot_id'])
        r['status']='CONSUMED'
        self.new(s,'visits',owner_id=r['owner_id'],vehicle_id=v['id'],spot_id=r['spot_id'],right_id=r['id'],status='PARKED',arrived_at=self.clock())
        for incident in s['incidents'].values():
            if incident.get('offered_right_id')==r['id']:
                incident.update(status='RESOLVED',response='Reception confirmed by simulated evidence.')

    def apply_evidence(self,s,cmd,observed):
        kind=cmd['kind']
        if kind=='TRANSFER':
            self.apply_transfer(s,cmd,observed)
        elif kind=='PICKUP':
            h=s['holds'][cmd['record_id']]; v=s['vehicles'][h['vehicle_id']]
            require(h['status']=='HANDOVER_PENDING','INVALID_STATE','Hold is not pending.')
            require(self.pickup_ready(s,v,self.clock()),'UNSAFE_PICKUP','Vehicle no longer suitable for pickup.')
            self.departure_effect(s,v['id'],cmd['spot_id'],observed)
            h['status']='CONSUMED'
            self.new(s,'trips',owner_id=h['owner_id'],vehicle_id=v['id'],hold_id=h['id'],status='OPEN',started_at=self.clock(),ended_at=None)
        elif kind in ('ARRIVAL','RETURN'):
            r=s['rights'][cmd['right_id'] if kind=='RETURN' else cmd['record_id']]
            self.arrival_effect(s,r,observed)
            if kind=='RETURN':
                t=s['trips'][cmd['record_id']]
                require(t['status']=='HANDOVER_PENDING','INVALID_STATE','Trip is not pending return.')
                t.update(status='CLOSED',ended_at=self.clock(),destination_hub_id=r['hub_id'])
        elif kind=='DEPARTURE':
            visit=s['visits'][cmd['record_id']]
            require(visit['status']=='HANDOVER_PENDING','INVALID_STATE','Departure is not pending.')
            self.departure_effect(s,visit['vehicle_id'],visit['spot_id'],observed)
        else:
            c=s['sessions'][cmd['record_id']]; port=s['ports'][c['port_id']]; v=s['vehicles'][c['vehicle_id']]
            self.stamp(port,observed)
            require(kind in ('PLUG','START','STOP','UNPLUG'),'UNKNOWN_EFFECT','Unrecognized device command.')
            if kind in ('PLUG', 'START'):
                self.check_charge_resources(s, v['id'], port)
            if kind=='PLUG':
                require(c['status']=='BOOKED' and v['spot_id']==port['spot_id'] and port['plug']=='UNPLUGGED'
                        and port['power']=='OFF' and port['health']=='OPERABLE','INVALID_CONNECTION','Connection prerequisites changed.')
                port.update(plug='CONNECTED',vehicle_id=v['id'])
            elif kind=='START':
                require(c['status']=='START_PENDING' and port['plug']=='CONNECTED' and port['vehicle_id']==v['id']
                    and port['health']=='OPERABLE' and self.clock()<c['scheduled_end'],'INVALID_START','Start prerequisites changed; reconcile and stop if needed.')
                running=sum(x['kw'] for x in s['sessions'].values() if x['status'] in ('START_PENDING','CHARGING','STOP_PENDING') and x['id']!=c['id'] and s['ports'][x['port_id']]['hub_id']==port['hub_id'])
                require(running+c['kw']<=s['hubs'][port['hub_id']]['power_kw'],'POWER_CONFLICT','Hub running power limit exceeded.')
                if v['kind']=='shared': require(not self.vehicle_claimed(s,v['id']),'VEHICLE_CLAIMED','Fleet vehicle now claimed.')
                c.update(status='CHARGING',started_at=self.clock())
                port['power']='ON'
            elif kind=='STOP':
                require(c['status']=='STOP_PENDING' and port['vehicle_id']==v['id'],'INVALID_STOP','Stop does not match current session.')
                port['power']='OFF'
                c.update(status='COMPLETED',completed_at=self.clock())
                # A stop ACK proves power off, not target SOC. SOC changes only
                # through an explicit observation, never an elapsed-time guess.
                for other in s['commands'].values():
                    if other['record_id']==c['id'] and other['kind']=='START' and other['status']=='PENDING': other['status']='SUPERSEDED'
            elif kind=='UNPLUG':
                require(port['power']=='OFF' and port['vehicle_id']==v['id'] and port['plug']=='CONNECTED','INVALID_UNPLUG','Cannot unplug without verified power off.')
                port.update(plug='UNPLUGGED',vehicle_id=None)

    def reject_evidence(self,s,cmd):
        kind=cmd['kind']; rid=cmd['record_id']
        if kind=='TRANSFER': self.reject_transfer(s,cmd)
        elif kind=='PICKUP': s['holds'][rid]['status']='ACTIVE'
        elif kind=='ARRIVAL': s['rights'][rid]['status']='CONFIRMED'
        elif kind=='RETURN':
            s['trips'][rid]['status']='OPEN'; s['rights'][cmd['right_id']]['status']='CONFIRMED'
        elif kind=='DEPARTURE': s['visits'][rid]['status']='PARKED'
        elif kind=='START':
            c=s['sessions'][rid]
            require(c['status']=='START_PENDING','INVALID_STATE','Start has already been superseded.')
            c['status']='BOOKED'
        elif kind=='STOP':
            self.incident(s,cmd['owner_id'],rid,'Device refused stop; power state remains unresolved.','stop-rejected-'+rid)
            # Rejected stop remains unresolved. Never free the connected port.
        elif kind not in ('PLUG','UNPLUG'): raise DomainError('UNKNOWN_EFFECT','Unknown rejected effect.')

    def expire(self,s):
        now=self.clock()
        before=copy.deepcopy(s_without_audit(s))
        for h in s['holds'].values():
            if h['status']=='ACTIVE' and h['expires_at']<=now:
                dependent=[r for r in s['rights'].values() if r.get('hold_id')==h['id'] and r['status'] in LIVE_RIGHT]
                if any(r['status']!='CONFIRMED' for r in dependent):
                    h['status']='HANDOVER_PENDING'
                    self.incident(s,h['owner_id'],h['id'],'Dependent handover pending at expiry.','hold-expiry-'+h['id'])
                else:
                    h['status']='EXPIRED'
                    for r in dependent: self.cancel_right(s,r,'EXPIRED')
        for r in s['rights'].values():
            if r['status']=='OFFERED' and r['start']+600<now:
                r['status']='EXPIRED'
                for i in s['incidents'].values():
                    if i.get('offered_right_id')==r['id']: i['status']='OPEN'
            if r['status']=='CONFIRMED' and r['start']+POLICY['no_show']<now:
                pending=any(c['vehicle_id']==r['vehicle_id'] and c['status']=='PENDING' for c in s['commands'].values())
                if not pending:
                    try: self.cancel_right(s,r,'EXPIRED')
                    except DomainError: pass
        for c in s['sessions'].values():
            port=s['ports'][c['port_id']]
            if c['status']=='BOOKED' and c['start']+POLICY['no_show']<now and not self.connected(s,c):
                c['status']='EXPIRED'
                r=s['rights'][c['right_id']]
                if c['created_parking'] and r['status']=='CONFIRMED': r['status']='EXPIRED'
            if c['status']=='CHARGING' and (now>=c['scheduled_end'] or s['vehicles'][c['vehicle_id']]['soc']>=c['target_soc']):
                c['status']='STOP_PENDING'
                self.request(s,'STOP',c,c['owner_id'],port_id=port['id'],vehicle_id=c['vehicle_id'])
            if c['status']=='COMPLETED' and now-c['completed_at']>POLICY['unplug_reminder'] and self.connected(s,c):
                self.incident(s,c['owner_id'],c['id'],'Charging stopped over 15 minutes ago; cable is still connected.','unplug-'+c['id'])
        for cmd in list(s['commands'].values()):
            if cmd['status']=='PENDING' and now-cmd['created_at']>POLICY['ack_timeout']:
                self.incident(s,cmd['owner_id'],cmd['record_id'],'No evidence after 60 seconds; claim retained for reconciliation.','pending-'+cmd['id'])
        for i in s['incidents'].values():
            if i['status']=='OPEN' and now-i['created_at']>300: i['escalated']=True
        self.advance_iot_charging(s)
        self.sync_charge_requests(s)
        after=s_without_audit(s)
        if before!=after:
            changed=[(k,rid,before[k].get(rid),r) for k in before for rid,r in after[k].items() if before[k].get(rid)!=r]
            self.log(s,'system','timers',[dict(kind=k,id=i,value=b) for k,i,b,n in changed], [dict(kind=k,id=i,value=n) for k,i,b,n in changed])


def s_without_audit(s):
    return {k:v for k,v in s.items() if k!='audit'}
