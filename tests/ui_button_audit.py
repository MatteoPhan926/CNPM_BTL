"""Browser-level smoke/regression audit against an isolated real HTTP server.

Run from project root: python -m tests.ui_button_audit (or python tests/ui_button_audit.py).
Requires Python Playwright and Chrome. No production database or credentials used.
Physical request regressions use explicitly labelled authenticated legacy API
calls; they are not reported as student UI buttons. IoT UI is tested separately.
"""
from __future__ import annotations

import json
import re
import argparse
import os
import sys
import tempfile
import threading
import traceback
import time
import uuid
from pathlib import Path
from io import BytesIO

from PIL import Image
import zxingcpp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from emobility.server import create_server


ROLES = ("alice", "bob", "operator", "dispatcher", "technician")
OP = {"id": "operator", "role": "operator"}
RESULTS = []


class Audit:
    def __init__(self, browser, name, simulator=True):
        self.name = name
        self.directory = tempfile.TemporaryDirectory()
        self.server = create_server(Path(self.directory.name) / "test.sqlite", simulator=simulator, port=0)
        self.service = self.server.service
        self.t = time.time()
        self.service.clock = lambda: self.t
        # Seed was made using the default clock; create a separate fixture before
        # start with a consistent time, preserving all production code paths.
        if simulator:
            self.service.command(OP, 'sim_refresh', {}, 'audit-initial-refresh')
        # Wait for HTTP request workers before removing the temporary database.
        self.server.daemon_threads = False
        self.server.block_on_close = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.browser = browser
        self.pages = {}
        self.contexts = []
        self.page_errors = []

    def close(self):
        try:
            for context in self.contexts:
                context.close()
        finally:
            # AppServer.close() already calls shutdown() and server_close().
            self.server.close()
            self.thread.join(10)
            if self.thread.is_alive():
                raise RuntimeError('Test HTTP server did not shut down')
            self.directory.cleanup()

    def record(self, status, label, details=""):
        row = {"case": self.name, "status": status, "step": label, "detail": details}
        RESULTS.append(row)
        print(json.dumps(row, ensure_ascii=True), flush=True)

    def check(self, label, condition, details=""):
        if not condition:
            self.record('FAIL', label, details)
            raise AssertionError(label + ': ' + str(details))
        self.record('PASS', label, details)

    def finding(self, label, condition, details=""):
        self.record('PASS' if condition else 'FINDING', label, details)

    def p(self, actor):
        if actor not in self.pages:
            context = self.browser.new_context(viewport={"width": 1350, "height": 850})
            self.contexts.append(context)
            page = context.new_page()
            page.set_default_timeout(5000)
            page.on('pageerror', lambda error: self.page_errors.append(str(error)))
            login_events = []
            page.on('request', lambda r: login_events.append('POST /api/login sent')
                    if r.url.endswith('/api/login') and r.method == 'POST' else None)
            page.on('requestfailed', lambda r: login_events.append(f'{r.method} /api/login failed: {r.failure}')
                    if r.url.endswith('/api/login') else None)
            try:
                page.goto(self.url, wait_until='load')
                expect(page.locator('#login-form')).to_be_visible(timeout=15000)
                page.locator('[name=username]').fill(actor)
                page.locator('[name=password]').fill(actor+'-demo')
                expect(page.locator('[name=username]')).to_have_value(actor)
                expect(page.locator('#login-form button[type=submit]')).to_be_enabled()
                with page.expect_response(
                    lambda r: r.url.endswith('/api/login') and r.request.method == 'POST',
                    timeout=15000
                ) as response:
                    page.locator('#login-form button[type=submit]').click()
                self.check(actor + ' Sign in', response.value.status == 200)
                expect(page.locator('#logout')).to_be_visible(timeout=15000)
            except Exception:
                print('[DEBUG] Login actor:', actor, flush=True)
                print('[DEBUG] Login network:', login_events, flush=True)
                print('[DEBUG] JavaScript errors:', self.page_errors, flush=True)
                if not page.is_closed():
                    try:
                        print('[DEBUG] Login feedback:', page.locator('#login-error').all_text_contents(), flush=True)
                    except Exception as diagnostic_error:
                        print('[DEBUG] Feedback unavailable:', type(diagnostic_error).__name__, flush=True)
                raise
            self.pages[actor] = page
        return self.pages[actor]

    def nav(self, actor, tab, sub=None):
        page = self.p(actor)
        page.locator(f'nav.nav button[data-tab="{tab}"]').click()
        if sub:
            page.locator(f'[data-fleet-section="{sub}"]').click()
        self.check(f'{actor} navigation {tab}' + (f'/{sub}' if sub else ''),
                   page.locator(f'nav.nav button[data-tab="{tab}"]').get_attribute('aria-current') == 'page')
        return page

    def refresh(self, actor):
        page = self.p(actor)
        with page.expect_response(lambda r:r.url.endswith('/api/state')) as response:
            page.locator('#refresh').click()
        self.check(actor+' Refresh', response.value.status == 200)
        page.wait_for_function('(expected) => !busy && !!state && state.revision === expected.revision && state.now === expected.now', arg=response.value.json())
        return page

    def snapshot(self):
        return self.service.snapshot(OP)

    def rows(self, collection):
        return self.snapshot()[collection]

    def row(self, collection, identifier):
        return next(r for r in self.rows(collection) if r['id'] == identifier)

    def action(self, actor, action, selector=None, error=None, outcome=None):
        page = self.p(actor)
        locator = selector if selector is not None else page.locator(f'button[data-action="{action}"]')
        expect(locator).to_be_enabled()
        label = locator.inner_text().strip()
        with page.expect_response(lambda r:r.url.endswith('/api/commands')) as result:
            locator.click()
        response = result.value
        data = response.json()
        page.wait_for_function('() => !busy')
        expect(page.locator('#notice')).to_be_visible()
        if error:
            self.check(f'{actor} {label} [reject {error}]', response.status >= 400 and data['error']['code'] == error,
                       str(data))
        else:
            self.check(f'{actor} {label}', response.status == 200 and (outcome is None or data.get('record',{}).get('status') == outcome),
                       str(data.get('record',{}).get('status',data.get('error',''))))
        RESULTS[-1]['action'] = action
        RESULTS[-1]['actor'] = actor
        return data.get('record',data)

    def legacy_api(self, actor, action, values=None, error=None, outcome=None):
        """Exercise preserved HTTP request contracts, never fake a UI click."""
        page = self.p(actor)
        response = page.request.post(self.url+'/api/commands',
            headers={'Origin':self.url}, data={'action':action,'payload':values or {},'intent_id':uuid.uuid4().hex})
        data = response.json()
        if error:
            self.check(f'Legacy API {actor} {action} rejects {error}',
                       response.status >= 400 and data.get('error',{}).get('code')==error, str(data))
        else:
            self.check(f'Legacy API {actor} {action}', response.status==200 and
                       (outcome is None or data.get('record',{}).get('status')==outcome),str(data))
        RESULTS[-1].update(action=action,actor=actor,interface='LEGACY_HTTP_API')
        if not page.locator('dialog[open]').count():
            self.refresh(actor)
        return data.get('record',data)

    def legacy_button(self, actor, action, key, value, **kw):
        payload = {key:value}
        if action == 'arrive':
            payload['qr_token'] = self.row('rights',value)['qr']['token']
        return self.legacy_api(actor,action,payload,**kw)

    def submit(self, actor, action, values=None, checks=None, **kw):
        page = self.p(actor)
        form = page.locator(f'form[data-command="{action}"]')
        for field, value in (values or {}).items():
            loc = form.locator(f'[name="{field}"]')
            if loc.evaluate('(e)=>e.tagName') == 'SELECT':
                loc.select_option(str(value))
            else:
                loc.fill(str(value))
        for field, value in (checks or {}).items():
            form.locator(f'[name="{field}"][value="{value}"]').check() if isinstance(value,str) else form.locator(f'[name="{field}"]').set_checked(value)
        return self.action(actor, action, form.locator('button[type=submit]'), **kw)

    def button(self, actor, action, key, value, **kw):
        page = self.p(actor)
        buttons=page.locator(f'button[data-action="{action}"]')
        for b in buttons.all():
            if json.loads(b.get_attribute('data-payload')).get(key)==value:
                return self.action(actor, action, b, **kw)
        raise AssertionError(f'Button not found: {actor} {action} {key}={value}')

    def ack(self, kind, outcome='ACK', record=None):
        self.nav('operator','operations')
        self.refresh('operator')
        cmd = next(c for c in self.rows('commands') if c['kind']==kind and c['status']=='PENDING' and (record is None or c['record_id']==record))
        page = self.p('operator')
        for b in page.locator('button[data-action="simulate"]').all():
            p = json.loads(b.get_attribute('data-payload'))
            if p['command_id']==cmd['id'] and p['outcome']==outcome:
                result = self.action('operator', 'simulate', b, outcome={'ACK':'ACKNOWLEDGED','REJECT':'REJECTED','UNKNOWN':'PENDING'}[outcome])
                return result
        raise AssertionError('No evidence button for '+kind)

    def booking(self, actor='alice', hub='H2', vehicle='P1', charging=False, start_offset=0, target=70, **kw):
        page = self.nav(actor,'parking')
        start=page.evaluate('(t)=>inputDate(t)', self.t+start_offset)
        end=page.evaluate('(t)=>inputDate(t)', self.t+start_offset+3600)
        return self.submit(actor,'reserve_parking', {'vehicle_id':vehicle,'hub_id':hub,'start':start,'end':end,'target_soc':target}, {'charging':charging}, **kw)

    def counter(self, actor, expected, label, refresh=False):
        page = self.nav(actor, 'overview')
        if refresh:
            self.refresh(actor)
        actual = page.locator('.stat .number').last.inner_text()
        backend = self.service.snapshot({'id': actor, 'role': 'student'})['active_services']
        self.check(label, actual == str(expected) and backend == expected,
                   f'UI={actual}; backend={backend}; expected={expected}')


def rentals(a):
    alice=a.nav('alice','overview'); bob=a.nav('bob','overview')
    a.check('Initial dashboard 3 / 3 / 27 / 0',alice.locator('.stat .number').all_inner_texts()==['3','3','27','0'])
    alice.locator('#hub-filter').select_option('H2')
    a.check('Filter H2',alice.locator('tbody tr').count()==1)
    alice.locator('[data-hub="H1"]').click()
    a.check('View vehicles H1',alice.locator('tbody tr').count()==2)
    h = a.button('alice','reserve_vehicle','vehicle_id','V1',outcome='ACTIVE')
    # Bob's UI may already have removed the button during background polling.
    # Exercise the conflicting request through the authenticated HTTP API.
    # legacy_api also refreshes Bob's page when no dialog is open.
    a.legacy_api('bob','reserve_vehicle',{'vehicle_id': 'V1'},error='VEHICLE_UNAVAILABLE')
    a.check('Bob cannot reserve V1 after Alice holds it', bob.locator(
        'button[data-action="reserve_vehicle"]'
    ).evaluate_all('buttons => !buttons.some(b => JSON.parse(b.dataset.payload).vehicle_id === "V1")'))
    a.nav('alice','journeys')
    a.button('alice','cancel_hold','hold_id',h['id'],outcome='CANCELLED')
    a.nav('bob','overview'); a.refresh('bob')
    h=a.button('bob','reserve_vehicle','vehicle_id','V1')
    a.nav('bob','journeys'); a.legacy_button('bob','pickup','hold_id',h['id'])
    a.ack('PICKUP','UNKNOWN'); a.ack('PICKUP','REJECT')
    a.refresh('bob'); a.legacy_button('bob','pickup','hold_id',h['id']); a.ack('PICKUP')
    trip=next(r for r in a.rows('trips') if r['owner_id']=='bob')
    a.check('Pickup creates OPEN trip and frees original bay',trip['status']=='OPEN' and a.row('spots','H1-S3')['state']=='EMPTY')
    a.nav('bob','journeys'); a.refresh('bob')
    a.legacy_api('bob','return_vehicle',{'trip_id':trip['id'],'hub_id':'H2'})
    a.ack('RETURN'); a.refresh('bob')
    a.check('Walk-in return closes journey',a.row('trips',trip['id'])['status']=='CLOSED' and a.row('vehicles','V1')['hub_id']=='H2')
    a.nav('bob','history'); expect(bob.locator('table')).to_be_visible()
    a.nav('alice','journeys'); a.refresh('alice')
    a.check('Alice cannot see Bob trip',not alice.get_by_text(trip['id'],exact=True).count())


def parking_charging(a):
    p=a.nav('alice','parking')
    vehicle=a.submit('alice','register_vehicle',{'label':'Audit bike','battery_kwh':2,'soc':30,'connector':'TYPE2'})
    a.check('Personal vehicle persisted',vehicle['owner_id']=='alice')
    right=a.booking(); a.nav('alice','overview'); a.refresh('alice')
    a.check('Parking-only booking reflected in Your active services',p.locator('.stat .number').last.inner_text()=='1','Expected 1 after parking-only booking; observed '+p.locator('.stat .number').last.inner_text())
    a.nav('alice','parking')
    a.check('Booking provides QR for arrival per UC-B01',bool(right.get('qr',{}).get('token')))
    a.button('alice','cancel_parking','right_id',right['id'],outcome='CANCELLED')
    right=a.booking(charging=True); session=next(c for c in a.rows('sessions') if c['right_id']==right['id'])
    a.nav('alice','charging'); a.button('alice','cancel_charge','session_id',session['id'],outcome='CANCELLED')
    a.check('Cancel charging bundle cancels associated right',a.row('rights',right['id'])['status']=='CANCELLED')
    right=a.booking(charging=True); session=next(c for c in a.rows('sessions') if c['right_id']==right['id'])
    a.nav('alice','charging'); a.legacy_button('alice','plug','session_id',session['id'],error='NOT_PARKED')
    a.legacy_button('alice','start_charge','session_id',session['id'],error='NOT_CONNECTED')
    a.nav('alice','parking'); a.legacy_button('alice','arrive','right_id',right['id']); a.ack('ARRIVAL')
    visit=next(v for v in a.rows('visits') if v['right_id']==right['id'])
    a.check('Arrival marks correct bay occupied',a.row('spots',right['spot_id'])['state']=='OCCUPIED')
    a.nav('alice','charging'); a.refresh('alice'); a.legacy_button('alice','plug','session_id',session['id']); a.ack('PLUG')
    a.refresh('alice'); a.legacy_button('alice','start_charge','session_id',session['id']); a.ack('START')
    a.check('Charging ON',a.row('ports',session['port_id'])['power']=='ON')
    a.nav('alice','parking'); a.legacy_button('alice','depart','visit_id',visit['id'],error='CONNECTED')
    a.nav('alice','charging'); a.refresh('alice'); a.button('alice','stop_charge','session_id',session['id']); a.ack('STOP')
    a.check('Stop does not free occupied bay',a.row('spots',right['spot_id'])['state']=='OCCUPIED' and a.row('ports',session['port_id'])['power']=='OFF')
    a.refresh('alice'); a.legacy_button('alice','unplug','session_id',session['id']); a.ack('UNPLUG')
    a.nav('alice','parking'); a.refresh('alice'); a.legacy_button('alice','depart','visit_id',visit['id']); a.ack('DEPARTURE')
    a.check('Departure frees parking',a.row('spots',right['spot_id'])['state']=='EMPTY')


def active_services_and_qr(a):
    from emobility.domain import Service
    a.counter('alice', 0, 'Alice starts with no active services')
    a.counter('bob', 0, 'Bob starts with no active services')
    right = a.booking()
    a.counter('alice', 1, 'Parking creation updates counter without Refresh')
    a.counter('bob', 0, 'Alice parking does not count for Bob', refresh=True)
    page = a.nav('alice', 'parking')
    external_requests = []
    page.on('request', lambda req: external_requests.append(req.url) if req.url.startswith('http') and not req.url.startswith(a.url + '/') else None)

    def show_qr(row):
        page.locator(f'[data-parking-qr="{row["id"]}"]').click()
        expect(page.locator('#parking-qr-dialog')).to_be_visible()
        image = page.locator('.parking-qr-image')
        expect(image).to_be_visible()
        page.wait_for_function('() => document.querySelector(".parking-qr-image")?.complete')
        return page.locator('#parking-qr-token').input_value()

    token = show_qr(right)
    a.check('QR modal shows correct reservation metadata', all(
        text in page.locator('#parking-qr-content').inner_text()
        for text in (right['id'], right['vehicle_id'], right['spot_id'], 'Thời gian đến', 'Mã vào bãi có hiệu lực đến')))
    decoded = zxingcpp.read_barcode(Image.open(BytesIO(page.locator('.parking-qr-image').screenshot())))
    a.check('Rendered QR decodes to persisted backend code', decoded is not None and decoded.text == token == right['qr']['token'])
    evidence = Path(__file__).resolve().parent / 'artifacts'
    evidence.mkdir(exist_ok=True)
    page.locator('#parking-qr-dialog').screenshot(path=str(evidence / 'parking_qr_desktop.png'))
    page.set_viewport_size({'width':390, 'height':844})
    decoded = zxingcpp.read_barcode(Image.open(BytesIO(page.locator('.parking-qr-image').screenshot())))
    a.check('Mobile QR remains decodable without modal horizontal overflow', decoded is not None and decoded.text == token and page.locator('#parking-qr-dialog').evaluate('(e)=>e.scrollWidth <= e.clientWidth'))
    page.locator('#parking-qr-dialog').screenshot(path=str(evidence / 'parking_qr_mobile.png'))
    page.locator('#close-parking-qr').click()
    a.check('Close dismisses QR modal', not page.locator('#parking-qr-dialog').is_visible())
    page.set_viewport_size({'width':1350, 'height':850})
    page.reload(); expect(page.locator('[data-parking-qr]').first).to_be_visible()
    a.check('QR survives browser reload', show_qr(right) == token)
    page.locator('#close-parking-qr').click()
    a.service = Service(a.service.db_path, simulator=True, clock=lambda: a.t)
    a.server.service = a.service
    a.refresh('alice')
    a.check('QR survives service restart with same DB', show_qr(right) == token)
    page.locator('#close-parking-qr').click()
    a.legacy_api('alice','arrive', {'qr_token':'emobility:parking:invalid'}, error='INVALID_QR')
    a.legacy_api('alice','arrive', {'qr_token':token}, outcome='HANDOVER_PENDING')
    a.check('QR check does not occupy bay or create visit', a.row('spots',right['spot_id'])['state']=='EMPTY' and not any(v['right_id']==right['id'] for v in a.rows('visits')))
    show_qr(right)
    expect(page.locator('#parking-qr-status')).to_contain_text('đang chờ bằng chứng tiếp nhận')
    a.check('Pending QR cannot request second check-in in modal', page.locator('#parking-qr-dialog button[data-action="arrive"]').count()==0)
    page.locator('#close-parking-qr').click()
    a.counter('alice', 1, 'Arrival pending remains one service')
    a.ack('ARRIVAL')
    a.refresh('alice'); a.counter('alice', 1, 'Right transitions to visit without double count')
    a.nav('alice','parking'); show_qr(right)
    expect(page.locator('#parking-qr-status')).to_contain_text('Mã đã được sử dụng')
    page.locator('#close-parking-qr').click()
    a.legacy_api('alice','arrive',{'qr_token':token},error='INVALID_RIGHT')
    visit = next(v for v in a.rows('visits') if v['right_id']==right['id'])
    a.legacy_button('alice','depart','visit_id',visit['id']); a.counter('alice',1,'Checkout pending remains active')
    a.ack('DEPARTURE'); a.refresh('alice'); a.counter('alice',0,'Verified checkout ends parking service')
    right = a.booking(); cancelled_token=right['qr']['token']
    a.button('alice','cancel_parking','right_id',right['id'])
    show_qr(right); expect(page.locator('#parking-qr-status')).to_contain_text('đã bị hủy')
    page.locator('#close-parking-qr').click()
    a.counter('alice',0,'Cancelled parking is not active')
    a.nav('alice','parking'); a.legacy_api('alice','arrive',{'qr_token':cancelled_token},error='INVALID_RIGHT')
    right = a.booking(); a.t += 601
    a.nav('operator','operations'); a.action('operator','sim_refresh'); a.refresh('alice')
    show_qr(right); expect(page.locator('#parking-qr-status')).to_contain_text('đã hết hạn')
    page.locator('#close-parking-qr').click()
    a.legacy_api('alice','arrive',{'qr_token':right['qr']['token']},error='INVALID_RIGHT')
    a.counter('alice',0,'Expired parking is not active')
    a.check('QR generation makes no external HTTP requests', not external_requests, repr(external_requests))
    hold = a.button('alice','reserve_vehicle','vehicle_id','V1')
    a.counter('alice',1,'Hold is one active rental')
    a.nav('alice','journeys'); a.legacy_button('alice','pickup','hold_id',hold['id']); a.ack('PICKUP'); a.refresh('alice')
    a.counter('alice',1,'Hold transitions to trip without double count')
    a.nav('alice','journeys')
    trip = next(t for t in a.rows('trips') if t['hold_id']==hold['id'])
    a.legacy_api('alice','return_vehicle',{'trip_id':trip['id'],'hub_id':'H3'}); a.ack('RETURN'); a.refresh('alice')
    a.counter('alice',0,'Returned fleet vehicle is not a remaining student service')


def bundle_service_counter(a):
    right = a.booking(charging=True)
    a.counter('alice',1,'Parking plus charging counts as one bundle')
    a.counter('bob',0,'Bundle is isolated from Bob',refresh=True)
    a.nav('operator','operations')
    a.submit('operator','sim_observe',{'resource_ref':'spots:'+right['spot_id'],'health':'OUT_OF_SERVICE'})
    page = a.nav('alice','parking')
    page.locator(f'[data-parking-qr="{right["id"]}"]').click()
    a.check('Student QR is presentation only',page.locator('#parking-qr-dialog button[data-action="arrive"]').count()==0)
    page.locator('#close-parking-qr').click()
    a.legacy_api('alice','arrive',dict(right_id=right['id'],qr_token=right['qr']['token']),error='RECEPTION_BLOCKED')
    # QR retrieval failures still need to be readable in the dialog now that
    # student-facing physical request controls have been removed.
    page.route('**/api/parking-qr?*',lambda route:route.fulfill(status=503,content_type='application/json',
        body=json.dumps({'error':{'code':'TEST_UNAVAILABLE','message':'QR temporarily unavailable'}})))
    page.locator(f'[data-parking-qr="{right["id"]}"]').click()
    expect(page.locator('#parking-qr-content')).to_contain_text('QR temporarily unavailable')
    a.check('QR retrieval error is readable inside modal',page.locator('#parking-qr-content').is_visible())
    page.locator('#close-parking-qr').click()
    page.unroute('**/api/parking-qr?*')
    a.submit('operator','sim_observe',{'resource_ref':'spots:'+right['spot_id'],'health':'OPERABLE'})
    a.legacy_api('alice','arrive',dict(right_id=right['id'],qr_token=right['qr']['token']),outcome='HANDOVER_PENDING')
    page.locator(f'[data-parking-qr="{right["id"]}"]').click()
    expect(page.locator('#parking-qr-status')).to_contain_text('đang chờ bằng chứng tiếp nhận')
    page.locator('#close-parking-qr').click()
    a.ack('ARRIVAL'); a.refresh('alice'); a.counter('alice',1,'Bundle stays one after arrival')
    session = next(s for s in a.rows('sessions') if s['right_id']==right['id'])
    a.nav('alice','charging'); a.legacy_button('alice','plug','session_id',session['id']); a.ack('PLUG'); a.refresh('alice')
    a.legacy_button('alice','start_charge','session_id',session['id']); a.ack('START'); a.refresh('alice')
    a.counter('alice',1,'Running charge and parking stay one bundle')
    a.nav('alice','charging'); a.button('alice','stop_charge','session_id',session['id']); a.ack('STOP'); a.refresh('alice')
    a.counter('alice',1,'Completed charging does not end occupied parking bundle')
    a.nav('alice','charging'); a.legacy_button('alice','unplug','session_id',session['id']); a.ack('UNPLUG'); a.refresh('alice')
    a.counter('alice',1,'Unplugged bundle stays active until departure')
    a.nav('alice','parking'); visit=next(v for v in a.rows('visits') if v['right_id']==right['id'])
    a.legacy_button('alice','depart','visit_id',visit['id']); a.ack('DEPARTURE'); a.refresh('alice')
    a.counter('alice',0,'Bundle finishes after all obligations end')
    right=a.booking(charging=True); a.button('alice','cancel_parking','right_id',right['id'])
    a.counter('alice',0,'Cancelled unused bundle counts zero')
    right=a.booking(charging=True); a.t+=601; a.refresh('alice')
    a.counter('alice',0,'Expired unused bundle counts zero')


def recovery(a):
    r=a.booking(start_offset=60)
    a.nav('alice','support'); incident=a.submit('alice','support',{'record_id':r['id'],'message':'Please suggest an alternative hub'})
    a.nav('operator','operations'); a.submit('operator','capacity_plan',{'incident_id':incident['id'],'hub_id':'H3','reason':'Alternative reception'},outcome='OFFERED')
    a.refresh('alice'); a.button('alice','accept_capacity','accept',False,outcome='DECLINED')
    a.refresh('operator'); a.submit('operator','capacity_plan',{'incident_id':incident['id'],'hub_id':'H3','reason':'Alternative reception'},outcome='OFFERED')
    a.refresh('alice'); a.button('alice','accept_capacity','accept',True,outcome='WAITING_FOR_RECEPTION')
    a.check('Accepted alternative cancels original right',a.row('rights',r['id'])['status']=='CANCELLED')


def fleet(a):
    p=a.nav('operator','network','network')
    p.locator('[data-resource-hub="H2"]').click()
    a.check('Inspect resources H2',p.locator('[data-resource-filter]').input_value()=='H2')
    p.locator('[data-resource-filter]').select_option('all')
    a.check('Filter all locations',p.locator('[data-resource-filter]').input_value()=='all')
    a.button('operator','d_resource_state','resource_id','H2-S4')
    a.check('Deactivated bay',a.row('spots','H2-S4')['health']=='DEACTIVATED')
    a.button('operator','d_resource_state','resource_id','H2-S4')
    a.check('Reactivated bay',a.row('spots','H2-S4')['health']=='OPERABLE')
    a.nav('operator','network','forecast')
    a.submit('operator','what_if',{'hub_id':'H1','demand_factor':3})
    a.action('operator','what_if_draft',p.locator('button[data-action="what_if_draft"]').first)
    a.nav('operator','network','transfers')
    form=p.locator('form[data-command="transfer_preview"]'); form.locator('[name=source_hub_id]').select_option('H2'); form.locator('[name=source_hub_id]').select_option('H1')
    form.locator('[name=dest_hub_id]').select_option('H2'); form.locator('[name=vehicle_ids][value=V1]').check(); form.locator('[name=vehicle_ids][value=V3]').check(); form.locator('[name=charging_bays]').check()
    order=a.action('operator','transfer_preview',form.locator('button[type=submit]'),outcome='DRAFT')
    a.button('operator','transfer_issue','order_id',order['id'],outcome='ISSUED')
    d=a.nav('dispatcher','network','transfers'); a.refresh('dispatcher')
    a.button('dispatcher','transfer_start','order_id',order['id'],outcome='IN_PROGRESS')
    a.submit('dispatcher','transfer_handover',checks={'vehicle_ids':'V1'})
    a.nav('operator','network','transfers'); a.refresh('operator')
    p.locator('#app main button[data-tab="operations"]').click()
    a.check('Open device outbox link',p.get_by_text('Danh sách lệnh thiết bị',exact=True).is_visible())
    a.ack('TRANSFER','REJECT'); a.refresh('dispatcher')
    a.submit('dispatcher','transfer_handover',checks={'vehicle_ids':'V1'}); a.ack('TRANSFER'); a.refresh('dispatcher')
    a.check('Partial transfer',a.row('orders',order['id'])['delivered']==['V1'])
    a.submit('dispatcher','transfer_handover',checks={'vehicle_ids':'V3'}); a.ack('TRANSFER'); a.refresh('dispatcher')
    a.check('Complete transfer',a.row('orders',order['id'])['status']=='COMPLETED' and all(a.row('vehicles',id)['hub_id']=='H2' for id in ['V1','V3']))
    a.nav('operator','operations'); a.refresh('operator'); a.submit('operator','fleet_charge',{'vehicle_id':'V1','target_soc':90},outcome='BOOKED')
    plan=a.action('operator','schedule_preview',outcome='DRAFT')
    p.locator(f'button[data-id="{plan["id"]}"]').click(); expect(p.locator('#detail-dialog')).to_be_visible(); p.locator('#close-dialog').click(); a.check('Review allocation and Close dialog',not p.locator('#detail-dialog').is_visible())
    a.button('operator','schedule_confirm','plan_id',plan['id'],outcome='APPLIED')
    a.nav('operator','charging'); a.refresh('operator')
    s=next(s for s in a.rows('sessions') if s['vehicle_id']=='V1')
    a.legacy_button('operator','plug','session_id',s['id']); a.ack('PLUG'); a.refresh('operator'); a.nav('operator','charging'); a.legacy_button('operator','start_charge','session_id',s['id']); a.ack('START')


def maintenance_telemetry(a):
    p=a.nav('operator','network','tickets')
    ticket=a.submit('operator','d_open_incident',{'resource_id':'H2-C1','message':'Connector inspection needed'},outcome='OPEN')
    t=a.nav('technician','network','tickets'); a.refresh('technician')
    f=t.locator('form[data-command="d_update_incident"]'); f.locator('[name=outcome]').select_option('RESOLVED'); f.locator('[name=note]').fill('Inspection completed successfully')
    a.check('Safety checkbox required',f.locator('[name=safety_passed]').is_visible() and f.locator('[name=safety_passed]').evaluate('(el)=>el.required'))
    f.locator('[name=safety_passed]').check(); a.action('technician','d_update_incident',f.locator('button[type=submit]'),outcome='RESOLVED')
    a.check('Repair restored charger',a.row('ports','H2-C1')['health']=='OPERABLE')
    a.refresh('operator'); ticket=a.submit('operator','d_open_incident',{'resource_id':'H3-C1','message':'Connector casing damaged'},outcome='OPEN')
    a.refresh('technician'); a.submit('technician','d_update_incident',{'outcome':'ESCALATED_WORKSHOP','note':'Part replacement at workshop'},outcome='ESCALATED_WORKSHOP')
    a.check('Escalation keeps resource isolated',a.row('ports','H3-C1')['health']=='OUT_OF_SERVICE')
    a.nav('operator','network','telemetry'); p.locator('#live-telemetry').uncheck(); p.locator('#live-telemetry').check()
    a.submit('operator','d_telemetry',{'resourceId':'V1','batterySoc':12,'speed':115,'temperatureC':27,'destinationHubId':'H2'})
    a.check('Telemetry changes SOC and records alerts',a.row('vehicles','V1')['soc']==12 and bool(a.row('vehicles','V1')['last_telemetry']['alerts']))
    a.service.command(OP,'d_telemetry',{'resourceId':'V2','event_id':uuid.uuid4().hex,'batterySoc':52,'speed':10},uuid.uuid4().hex)
    expect(p.locator('#telemetry-readings').get_by_text('52% pin',exact=False)).to_be_visible(timeout=7000)
    a.check('Live updates renders new reading without page Refresh',True)
    a.nav('operator','operations'); a.submit('operator','sim_observe',{'resource_ref':'spots:H1-S5','health':'OUT_OF_SERVICE'})
    a.check('Synthetic fault persisted',a.row('spots','H1-S5')['health']=='OUT_OF_SERVICE')
    a.submit('operator','sim_observe',{'resource_ref':'spots:H1-S5','health':'OPERABLE'})
    a.t+=91; a.nav('alice','overview'); a.refresh('alice')
    a.check('Stale dashboard shows zero availability',a.p('alice').locator('.stat .number').all_inner_texts()[1:3]==['0','0'])
    a.action('operator','sim_refresh',outcome='SIMULATED'); a.refresh('alice')
    a.check('Manual observation refresh restores parking',a.p('alice').locator('.stat .number').all_inner_texts()[2]=='26')


def roles_and_sessions(a):
    for actor in ROLES:
        p=a.p(actor)
        tabs=set(p.locator('nav.nav button').evaluate_all('(els)=>els.map(e=>e.dataset.tab)'))
        expected={'overview','journeys','parking','charging','support','history'} if actor in ('alice','bob') else {'overview','network','history'} if actor in ('dispatcher','technician') else {'overview','journeys','parking','charging','support','operations','network','history'}
        if actor=='operator' and a.server.service.simulator:
            expected.add('technical')
        a.check(actor+' tab visibility',tabs==expected,str(tabs))
        a.nav(actor,'history'); a.refresh(actor)
        with p.expect_response(lambda r:r.url.endswith('/api/logout')) as response:
            p.locator('#logout').click()
        expect(p.locator('#login-form')).to_be_visible()
        a.check(actor+' Sign out',response.value.status==200)


def no_simulator(a):
    p=a.nav('operator','operations')
    a.check('Simulation controls hidden when disabled',p.locator('button[data-action="sim_refresh"]').count()==0)
    a.nav('operator','network','telemetry'); a.check('No synthetic telemetry form when disabled',p.locator('form[data-command="d_telemetry"]').count()==0)
    p=a.nav('alice','overview'); a.check('No resource available without observations',p.locator('button[data-action="reserve_vehicle"]').count()==0)


def existing_right_and_reserved_return(a):
    p=a.nav('alice','parking')
    # A compatible independent right is supported by the backend. There is no
    # parking-bay picker in the current UI, so the initial fixture is explicit.
    first=a.service.command({'id':'alice','role':'student'},'reserve_parking',
        {'vehicle_id':'P1','hub_id':'H2','spot_id':'H2-S1','start':a.t,'end':a.t+3600},uuid.uuid4().hex)['record']
    a.refresh('alice'); a.nav('alice','charging')
    a.submit('alice','register_charge',{'right_id':first['id'],'target_soc':25},error='INVALID_TARGET')
    a.submit('alice','register_charge',{'right_id':first['id'],'target_soc':80},outcome='BOOKED')
    session=next(s for s in a.rows('sessions') if s['right_id']==first['id'])
    a.button('alice','cancel_charge','session_id',session['id'],outcome='CANCELLED')
    a.check('Added charging cancellation keeps independently booked parking',a.row('rights',first['id'])['status']=='CONFIRMED')
    p.locator('#app main button[data-tab="parking"]').click()
    a.check('Book parking + charging link opens Parking',p.locator('form[data-command="reserve_parking"]').is_visible())
    a.finding('Choose a specific bay in Parking UI',p.locator('form[data-command="reserve_parking"] [name=spot_id]').count()>0,'Backend supports spot_id; UI has no spot selector')
    a.finding('Parking UI has live availability preview',p.locator('form[data-command="reserve_parking"] button').filter(has_text=re.compile(r'Preview|Xem trước', re.I)).count()>0,'No preview control for selected time or charging compatibility')
    a.nav('alice','overview'); a.finding('Per-hub counts for ordinary and charging bays',p.locator('.hub-card').first.get_by_text(re.compile(r'charging spaces|chỗ đỗ có sạc|ô đỗ có sạc|chỗ đỗ sạc điện|ô đỗ sạc điện', re.I)).count()>0,'Hub cards show commitments, not the two free-bay categories')
    a.nav('alice','journeys'); p.locator('#app main button[data-tab="overview"]').click(); a.check('Find a vehicle opens Explore hubs',p.locator('#hub-filter').is_visible())
    h=a.button('alice','reserve_vehicle','vehicle_id','V1')
    a.nav('alice','journeys'); p.locator("#app main aside button.link.spaced[data-tab='parking']").click(); a.check('Reserve parking navigation',p.locator('form[data-command="reserve_parking"]').is_visible())
    right=a.booking(vehicle='V1',hub='H3'); a.nav('alice','journeys'); a.legacy_button('alice','pickup','hold_id',h['id']); a.ack('PICKUP'); a.refresh('alice')
    trip=next(t for t in a.rows('trips') if t['vehicle_id']=='V1')
    a.legacy_api('alice','return_vehicle',{'trip_id':trip['id'],'hub_id':'H3','right_id':right['id']}); a.ack('RETURN'); a.refresh('alice')
    a.check('Reserved return consumes correct right and closes trip',a.row('rights',right['id'])['status']=='CONSUMED' and a.row('trips',trip['id'])['status']=='CLOSED')


def uncertain_response_and_login(a):
    p=a.p('alice')
    # Lose the response after the real server commits, not before the request.
    def lose_response(route):
        response=route.fetch()
        assert response.status==200
        route.abort()
    p.route('**/api/commands',lose_response,times=1)
    p.locator('button[data-action="reserve_vehicle"]').first.click()
    expect(p.locator('#notice [data-notice=retry]')).to_be_visible()
    a.check('Network failure offers retry',len(a.rows('holds'))==1)
    with p.expect_response(lambda r:r.url.endswith('/api/commands')) as reply:
        p.locator('#notice [data-notice=retry]').click()
    p.wait_for_function('() => !busy')
    a.check('Retry same request retrieves receipt without duplicate hold',reply.value.status==200 and len(a.rows('holds'))==1)
    p.locator('#notice [data-notice=close]').click()

    expect(
        p.locator('#notice')
    ).to_be_hidden(timeout=2000)

    a.check(
        'Dismiss hides notification',
        not p.locator('#notice').is_visible()
    )
    with p.expect_response(lambda r:r.url.endswith('/api/logout')):
        p.locator('#logout').click()
    expect(p.locator('#login-form')).to_be_visible()
    p.locator('[name=username]').fill('alice'); p.locator('[name=password]').fill('invalid-demo-password')
    with p.expect_response(lambda r:r.url.endswith('/api/login')) as response:
        p.locator('#login-form button[type=submit]').click()
    expect(p.locator('#login-error')).not_to_be_empty()
    a.check('Incorrect password is rejected with login feedback',response.value.status==401)
    p.locator('[name=password]').fill('alice-demo')
    with p.expect_response(lambda r:r.url.endswith('/api/login')) as response:
        p.locator('#login-form button[type=submit]').click()
    expect(p.locator('#logout')).to_be_visible()
    a.check('Sign in again after error',response.value.status==200)


def full_hub_and_operator_controls(a):
    p=a.nav('operator','parking')
    a.finding('Operator UI hides student-only registration form',p.locator('form[data-command="register_vehicle"]').count()==0,'Registration is rendered for operator even though it requires student role')
    a.submit('operator','register_vehicle',{'label':'Operator test only','battery_kwh':2,'soc':30,'connector':'TYPE2'},error='FORBIDDEN')
    a.nav('operator','operations'); p.locator('#app main button[data-tab="charging"]').click(); a.check('Manage charging sessions link',p.locator('form[data-command="register_charge"]').is_visible())
    a.nav('operator','operations'); p.locator('#app main button[data-tab="support"]').click(); a.check('View support records link',p.locator('form[data-command="support"]').is_visible())
    a.nav('operator','operations'); p.locator('#app main button[data-tab="network"]').click(); a.check('Open fleet operations link',p.locator('#fleet-workspace').is_visible())
    # Use a deterministic fixture to exhaust destination capacity; the actual
    # return and booking attempts are initiated from the student's browser.
    for spot in a.rows('spots'):
        if spot['hub_id']=='H2' and spot['state']=='EMPTY':
            a.service.command(OP,'sim_observe',{'resource_type':'spots','resource_id':spot['id'],'health':'OUT_OF_SERVICE'},uuid.uuid4().hex)
    student=a.nav('alice','overview'); a.refresh('alice')
    h=a.button('alice','reserve_vehicle','vehicle_id','V1'); a.nav('alice','journeys'); a.legacy_button('alice','pickup','hold_id',h['id']); a.ack('PICKUP'); a.refresh('alice')
    trip=next(t for t in a.rows('trips') if t['vehicle_id']=='V1')
    a.legacy_api('alice','return_vehicle',{'trip_id':trip['id'],'hub_id':'H2'},outcome='ASSISTANCE_PENDING')
    a.check('Full hub preserves trip and creates incident',a.row('trips',trip['id'])['status']=='ASSISTANCE_PENDING' and any(i['record_id']==trip['id'] for i in a.rows('incidents')))
    a.booking(error='HUB_CAPACITY')
    a.finding('Full parking booking presents alternative hubs before confirmation',student.locator('form[data-command="reserve_parking"] [name=spot_id]').count()>0,'Server safely rejects HUB_CAPACITY but UI has no alternative-hub/availability preview')
    a.nav('alice','support'); a.check('Student can view incident generated by full return',student.get_by_text('Return assistance',exact=False).count()>0)


def responsive_and_stale_ui(a):
    p=a.nav('alice','overview')
    a.t+=91
    p.wait_for_function(
        """() => {
            const numbers = [
                ...document.querySelectorAll('.stat .number')
            ].slice(1, 3);

            return numbers.length === 2 &&
                numbers.every(e => e.textContent.trim() === '0');
        }""",
        timeout=15000
    )
    a.check('Overview reflects expired observations through polling',p.locator('.stat .number').all_inner_texts()[1:3]==['0','0'])
    a.refresh('alice')
    a.check('Manual Refresh reflects current availability',p.locator('.stat .number').all_inner_texts()[1:3]==['0','0'])
    a.finding('Student dashboard explicitly explains stale-zero capacity',p.locator('.mode-banner').get_by_text(re.compile(r'stale|dữ liệu đã cũ|dữ liệu quan sát đã cũ', re.I)).count()>0,'No distinct stale warning in mode banner; resource labels and footnotes still show STALE')
    p.set_viewport_size({'width':390,'height':844})
    for tab in ['overview','journeys','parking','charging','support','history']:
        a.nav('alice',tab)
        a.finding(f'Mobile width 390: {tab} no document overflow',p.evaluate('document.documentElement.scrollWidth <= innerWidth'),str(p.evaluate('({width:innerWidth, scrollWidth:document.documentElement.scrollWidth})')))


def cloud_adapter(a):
    from http.client import HTTPConnection
    from emobility.cloud_server import CloudHandler
    # Exercise the local adapter with the headers a TLS-terminating Render
    # proxy would deliver. No real deployment or external site is contacted.
    host='audit-test.onrender.com'
    previous=os.environ.get('RENDER_EXTERNAL_HOSTNAME')
    os.environ['RENDER_EXTERNAL_HOSTNAME']=host
    a.server.RequestHandlerClass=CloudHandler
    cookie=''
    def api(path,data=None,authenticated=False):
        conn=HTTPConnection('127.0.0.1',a.server.server_port,timeout=5)
        headers={'Host':host,'Origin':'https://'+host,'Content-Type':'application/json'}
        if authenticated: headers['Cookie']=cookie
        try:
            conn.request('POST' if data is not None else 'GET',path,body=json.dumps(data) if data is not None else None,headers=headers)
            r=conn.getresponse(); return r.status,json.loads(r.read()),r.getheader('Set-Cookie')
        finally: conn.close()
    try:
        status,data,_=api('/api/health'); a.check('Cloud handler health',status==200 and data['simulator'])
        for actor in ROLES:
            status,data,header=api('/api/login',{'username':actor,'password':actor+'-demo'})
            a.check('Cloud adapter login '+actor,status==200 and data['actor']['id']==actor and '; Secure' in header and 'HttpOnly' in header)
            cookie=header.split(';')[0]
            status,state,_=api('/api/state',authenticated=True)
            a.check('Cloud adapter snapshot '+actor,status==200 and state['actor']['id']==actor)
            status,_,_=api('/api/logout',{},True); a.check('Cloud adapter logout '+actor,status==200)
    finally:
        a.server.RequestHandlerClass=__import__('emobility.server',fromlist=['Handler']).Handler
        if previous is None: os.environ.pop('RENDER_EXTERNAL_HOSTNAME',None)
        else: os.environ['RENDER_EXTERNAL_HOSTNAME']=previous


def static_preview(a):
    context=a.browser.new_context(viewport={'width':1350,'height':850}); a.contexts.append(context)
    p=context.new_page(); p.set_default_timeout(5000)
    p.on('pageerror',lambda error:a.page_errors.append(str(error)))
    p.goto((Path(__file__).resolve().parents[1]/'deploy-demo'/'index.html').as_uri())
    for actor in ROLES:
        expect(p.locator('#login-form')).to_be_visible()
        p.locator('[name=username]').fill(actor); p.locator('[name=password]').fill(actor+'-demo'); p.locator('#login-form button[type=submit]').click()
        expect(p.locator('#logout')).to_be_visible(); a.check('Static preview login '+actor,True)
        if actor=='alice':
            p.locator('button[data-action="reserve_vehicle"]').first.click(); expect(p.locator('#notice')).to_be_visible(); a.check('Static preview reservation displays outcome',not p.locator('#notice').get_attribute('class').endswith('error'))
        p.locator('#logout').click(); expect(p.locator('#login-form')).to_be_visible(); a.check('Static preview logout '+actor,True)
    p.get_by_role('button',name='Reset demo',exact=True).click(); expect(p.locator('#login-form')).to_be_visible(); a.check('Static preview Reset demo',True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cases',nargs='*',help='Only run named scenarios; default: all')
    parser.add_argument('--report',type=Path,help='Optional JSON file for the complete audit results')
    args=parser.parse_args()
    for actor in ROLES:
        os.environ[f'EMOBILITY_{actor.upper()}_PASSWORD']=actor+'-demo'
    cases=[rentals,parking_charging,active_services_and_qr,bundle_service_counter,recovery,fleet,maintenance_telemetry,roles_and_sessions,no_simulator,existing_right_and_reserved_return,uncertain_response_and_login,full_hub_and_operator_controls,responsive_and_stale_ui,cloud_adapter,static_preview]
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(channel='chrome',headless=True)
        for case in cases:
            if args.cases and case.__name__ not in args.cases: continue
            a=Audit(browser,case.__name__,simulator=case is not no_simulator)
            try:
                case(a)
                a.check('No browser JavaScript exceptions',not a.page_errors,repr(a.page_errors))
            except Exception as error:
                a.record('FAIL','Scenario aborted',f'{type(error).__name__}: {error}')
                traceback.print_exc()
            finally:
                a.close()
        browser.close()
    from collections import Counter
    summary=dict(Counter(row['status'] for row in RESULTS))
    print('SUMMARY',summary,flush=True)
    print('ACTION COVERAGE', sorted({r['action'] for r in RESULTS if 'action' in r}), flush=True)
    if args.report:
        args.report.write_text(json.dumps({'summary':summary,'results':RESULTS},ensure_ascii=False,indent=2),encoding='utf-8')
    sys.exit(1 if any(row['status']=='FAIL' for row in RESULTS) else 0)
