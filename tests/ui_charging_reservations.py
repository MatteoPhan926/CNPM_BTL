"""Real-browser charging-only approval, QR decoding and physical lifecycle.

Run: python tests/ui_charging_reservations.py
Uses isolated temporary databases and the real HTTP API.
QR presentation and approval are exercised through the UI. Physical request
compatibility calls are explicitly labelled legacy API; IoT UI has its own suite.
"""
from collections import Counter
from io import BytesIO
import json
import os
from pathlib import Path
import traceback

from PIL import Image
import zxingcpp
from playwright.sync_api import sync_playwright, expect
from ui_button_audit import Audit, RESULTS, ROLES


def show_qr(a, page, kind, identifier, token):
    page.locator(f'[data-service-qr="{kind}"][data-id="{identifier}"]').click()
    picture = page.locator('#service-qr-content img')
    expect(picture).to_be_visible()
    decoded = zxingcpp.read_barcode(Image.open(BytesIO(picture.screenshot())))
    a.check(kind+' actual QR decodes to durable backend token', decoded is not None and decoded.text == token)
    page.set_viewport_size({'width':390,'height':844})
    decoded = zxingcpp.read_barcode(Image.open(BytesIO(picture.screenshot())))
    a.check(kind+' mobile QR readable without horizontal overflow', decoded is not None and decoded.text == token and
            page.locator('#service-qr-dialog').evaluate('(e)=>e.scrollWidth <= e.clientWidth'))
    artifacts = Path(__file__).parent / 'artifacts'
    artifacts.mkdir(exist_ok=True)
    page.locator('#service-qr-dialog').screenshot(path=str(artifacts / (kind+'_qr_mobile.png')))
    page.set_viewport_size({'width':1350,'height':850})


def charging_only(a):
    page = a.nav('alice','charging')
    form = page.locator('form[data-command="submit_charge_request"]')
    names = form.locator('input,select').evaluate_all('(els)=>els.map(e=>e.name).sort()')
    a.check('Charging only asks exactly the five specified fields', names == sorted([
        'vehicle_id','hub_id','declared_soc','target_soc','arrival_time']))
    a.check('Vehicle dropdown contains only Alice personal vehicles',
            form.locator('select[name=vehicle_id] option').evaluate_all('(els)=>els.map(e=>e.value)') == ['', 'P1'])
    arrival = page.evaluate('(t)=>inputDate(t)', a.t)
    request = a.submit('alice','submit_charge_request', dict(vehicle_id='P1',hub_id='H1',declared_soc=20,
                                                          target_soc=80,arrival_time=arrival),outcome='PENDING')
    a.check('Pending request allocates no right or session and shows no QR',
            not a.rows('rights') and not a.rows('sessions') and page.locator('[data-service-qr=charging]').count()==0)
    op = a.nav('operator','operations')
    a.check('Operator sees calculated energy duration and collection estimate', all(
        text in op.inner_text('main') for text in ['Energy required:', 'Estimated duration:', 'Expected collection:', 'Requested by alice']))
    booked = a.button('operator','approve_charge_request','request_id',request['id'],outcome='BOOKED')
    a.refresh('alice')
    a.check('Student sees confirmed allocation and estimates', all(text in page.inner_text('main') for text in [
        booked['spot_id'],booked['port_id'],'Estimated charging end:','Expected collection:']))
    show_qr(a,page,'charging',booked['id'],booked['qr']['token'])
    a.check('Charging QR has no student scan action',page.locator('#service-qr-dialog button[data-action]').count()==0)
    a.legacy_api('alice','scan_charge',dict(request_id=booked['id'],qr_token=booked['qr']['token']))
    a.check('QR scan requests reception without claiming physical arrival',
            a.row('spots',booked['spot_id'])['state']=='EMPTY')
    page.locator('#close-service-qr').click()
    a.ack('ARRIVAL'); a.refresh('alice')
    sid = booked['session_id']
    for action, kind in [('plug','PLUG'),('start_charge','START'),('stop_charge','STOP')]:
        if action == 'stop_charge':
            a.button('alice',action,'session_id',sid)
        else:
            a.legacy_button('alice',action,'session_id',sid)
        a.ack(kind); a.refresh('alice')
    a.check('Completed charging still occupies the bay and prompts collection',
            a.row('spots',booked['spot_id'])['state']=='OCCUPIED' and 'Please collect your vehicle' in page.inner_text('main'))
    a.legacy_button('alice','unplug','session_id',sid); a.ack('UNPLUG'); a.refresh('alice')
    visit = next(v for v in a.rows('visits') if v.get('right_id')==booked['right_id'])
    a.legacy_button('alice','depart','visit_id',visit['id'])
    a.check('Departure request keeps bay until ACK',a.row('spots',booked['spot_id'])['state']=='OCCUPIED')
    a.ack('DEPARTURE'); a.refresh('alice')
    a.check('Departure evidence frees bay',a.row('spots',booked['spot_id'])['state']=='EMPTY')
    page.set_viewport_size({'width':390,'height':844})
    a.check('Charging page responsive at 390px',page.evaluate('document.documentElement.scrollWidth <= innerWidth'))


def rejection_and_cancellation(a):
    page = a.nav('alice','charging')
    data = dict(vehicle_id='P1',hub_id='H1',declared_soc=30,target_soc=80,
                arrival_time=page.evaluate('(t)=>inputDate(t)',a.t))
    request = a.submit('alice','submit_charge_request',data)
    a.nav('operator','operations')
    a.submit('operator','reject_charge_request',{'reason':'No capacity for this request'},outcome='REJECTED')
    a.refresh('alice')
    a.check('Student sees rejection reason', 'No capacity for this request' in page.inner_text('main'))
    request = a.submit('alice','submit_charge_request',data)
    a.refresh('operator')
    a.button('operator','approve_charge_request','request_id',request['id'])
    a.refresh('alice')
    a.button('alice','cancel_charge_request','request_id',request['id'],outcome='CANCELLED')
    a.check('Cancelled charging booking releases both allocations', all(r['status']=='CANCELLED' for r in a.rows('rights')) and
            all(s['status']=='CANCELLED' for s in a.rows('sessions')))


def rental_confirmation(a):
    page = a.nav('alice','overview')
    hold = a.button('alice','reserve_vehicle','vehicle_id','V1')
    a.nav('alice','journeys')
    show_qr(a,page,'rental',hold['id'],hold['qr']['token'])
    a.check('Rental QR has no student scan action',page.locator('#service-qr-dialog button[data-action]').count()==0)
    a.legacy_api('alice','scan_rental',dict(hold_id=hold['id'],qr_token=hold['qr']['token']))
    a.check('Rental QR waits for physical pickup evidence',not a.rows('trips'))
    page.locator('#close-service-qr').click()
    a.ack('PICKUP'); a.refresh('alice')
    a.check('Pickup ACK creates exactly one journey',len(a.rows('trips'))==1)


if __name__ == '__main__':
    for actor in ROLES:
        os.environ[f'EMOBILITY_{actor.upper()}_PASSWORD'] = actor+'-demo'
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome',headless=True)
        for case in (charging_only,rejection_and_cancellation,rental_confirmation):
            audit = Audit(browser,case.__name__)
            try:
                case(audit)
                audit.check('No browser JavaScript exceptions',not audit.page_errors,repr(audit.page_errors))
            except Exception as error:
                audit.record('FAIL','Scenario aborted',str(error))
                traceback.print_exc()
            finally:
                audit.close()
        browser.close()
    summary = dict(Counter(row['status'] for row in RESULTS))
    print('SUMMARY',summary)
    Path(__file__).with_name('charging_ui_results.json').write_text(json.dumps(
        {'summary':summary,'results':RESULTS},indent=2),encoding='utf-8')
    raise SystemExit(1 if summary.get('FAIL') else 0)
