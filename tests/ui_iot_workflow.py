"""Browser journeys through the technical simulator; no student physical requests."""
from collections import Counter
import json
import os
from pathlib import Path
import traceback

from playwright.sync_api import sync_playwright, expect
from ui_button_audit import Audit, RESULTS, ROLES


def student_status(a, collection, identifier, status):
    page = a.p('alice')
    page.wait_for_function('([kind,id,status])=>state?.[kind]?.some(r=>r.id===id&&r.status===status)',
                          arg=[collection,identifier,status],timeout=15000)
    a.check('Student automatically observes '+collection+' '+status,True)


def scan(a, record, token, hub, spot):
    a.nav('operator','technical')
    a.refresh('operator')
    return a.submit('operator','sim_iot_scan',dict(qr_token=token,vehicle_id=record['vehicle_id'],hub_id=hub,spot_id=spot))


def event(a, kind, record, hub, spot='', port=''):
    a.nav('operator','technical'); a.refresh('operator')
    return a.submit('operator','sim_iot_event',dict(kind=kind,record_id=record['id'],
        vehicle_id=record['vehicle_id'],hub_id=hub,spot_id=spot,port_id=port))


def no_physical_controls(a, page):
    actions=['pickup','arrive','depart','return_vehicle','plug','unplug','start_charge','scan_charge','scan_rental']
    for tab in ['journeys','parking','charging']:
        a.nav('alice',tab)
        a.check('No redundant student physical controls in '+tab,all(
            page.locator(f'[data-action="{action}"],form[data-command="{action}"]').count()==0 for action in actions))
    a.check('Student cannot access technical simulator navigation',page.locator('nav [data-tab=technical]').count()==0)


def charging(a):
    page = a.nav('alice','charging')
    no_physical_controls(a,page)
    request = a.submit('alice','submit_charge_request',dict(vehicle_id='P1',hub_id='H2',declared_soc=20,
        target_soc=80,arrival_time=page.evaluate('(t)=>inputDate(t)',a.t)))
    a.nav('operator','operations')
    booked = a.button('operator','approve_charge_request','request_id',request['id'])
    student_status(a,'charge_requests',request['id'],'BOOKED')
    page.locator(f'[data-service-qr=charging][data-id="{request["id"]}"]').click()
    expect(page.locator('#service-qr-content img')).to_be_visible()
    a.check('QR is presentation only with reader instructions',
        page.locator('#service-qr-dialog [data-action]').count()==0 and
        'Xuất trình mã QR tại trạm hoặc ô đỗ được chỉ định.' in ' '.join(page.locator('#service-qr-content').inner_text().split()))
    a.check('Opening QR creates no physical command',not a.rows('commands'))
    page.locator('#close-service-qr').click()
    # A background state update must not erase a user editing a separate form.
    page.locator('form[data-command=submit_charge_request] [name=declared_soc]').fill('47')
    scan(a,booked,booked['qr']['token'],'H2',booked['spot_id'])
    student_status(a,'rights',booked['right_id'],'HANDOVER_PENDING')
    a.check('Polling preserves form draft',page.locator('form[data-command=submit_charge_request] [name=declared_soc]').input_value()=='47')
    a.check('Scan alone does not occupy bay',a.row('spots',booked['spot_id'])['state']=='EMPTY')
    a.ack('ARRIVAL')
    student_status(a,'rights',booked['right_id'],'CONSUMED')
    session = a.row('sessions',booked['session_id'])
    event(a,'PLUG',session,'H2',booked['spot_id'],session['port_id'])
    student_status(a,'sessions',session['id'],'START_PENDING')
    a.check('Connection initiates START but power awaits ACK',a.row('ports',session['port_id'])['power']=='OFF')
    a.ack('START'); student_status(a,'sessions',session['id'],'CHARGING')
    a.legacy_api('operator','sim_observe',dict(resource_type='vehicles',resource_id='P1',soc=80))
    student_status(a,'sessions',session['id'],'STOP_PENDING')
    a.ack('STOP'); student_status(a,'sessions',session['id'],'COMPLETED')
    a.check('Completion keeps bay and offers collection guidance',
        a.row('spots',booked['spot_id'])['state']=='OCCUPIED' and 'Vui lòng ngắt kết nối sạc và đưa phương tiện ra khỏi ô đỗ.' in ' '.join(page.inner_text('main').split()))
    event(a,'UNPLUG',session,'H2',booked['spot_id'],session['port_id'])
    visit = next(v for v in a.rows('visits') if v.get('right_id')==booked['right_id'])
    event(a,'DEPARTURE',visit,'H2',visit['spot_id'])
    student_status(a,'visits',visit['id'],'DEPARTED')
    a.check('Device departure frees bay',a.row('spots',visit['spot_id'])['state']=='EMPTY')
    page.set_viewport_size({'width':390,'height':844})
    a.check('Student charging remains responsive',page.evaluate('document.documentElement.scrollWidth<=innerWidth'))


def rental(a):
    page = a.nav('alice','overview')
    hold = a.button('alice','reserve_vehicle','vehicle_id','V1')
    a.nav('alice','journeys')
    scan(a,hold,hold['qr']['token'],'H1','H1-S3')
    a.ack('PICKUP'); student_status(a,'holds',hold['id'],'CONSUMED')
    trip = next(t for t in a.rows('trips') if t['vehicle_id']=='V1')
    a.submit('alice','select_return_hub',dict(trip_id=trip['id'],hub_id='H2'))
    a.check('Saving destination does not start physical return',a.row('trips',trip['id'])['status']=='OPEN' and
            not any(c['kind']=='RETURN' for c in a.rows('commands')))
    pending = event(a,'RETURN_PREPARE',trip,'H2')
    right = a.row('rights',pending['return_right_id'])
    student_status(a,'trips',trip['id'],'HANDOVER_PENDING')
    event(a,'RETURN',trip,'H2',right['spot_id'])
    student_status(a,'trips',trip['id'],'CLOSED')
    a.check('Return device evidence positions vehicle',a.row('vehicles','V1')['hub_id']=='H2')


def parking_and_add(a):
    page = a.nav('alice','parking')
    right = a.booking()
    scan(a,right,right['qr']['token'],right['hub_id'],right['spot_id'])
    a.ack('ARRIVAL'); student_status(a,'rights',right['id'],'CONSUMED')
    visit = next(v for v in a.rows('visits') if v.get('right_id')==right['id'])
    event(a,'DEPARTURE',visit,'H2',right['spot_id'])
    student_status(a,'visits',visit['id'],'DEPARTED')
    # Fixture selects a charging-capable bay via the unchanged API, since the
    # Parking-only UI intentionally prefers ordinary bays.
    right = a.legacy_api('alice','reserve_parking',dict(vehicle_id='P1',hub_id='H2',spot_id='H2-S1',start=a.t,end=a.t+3600))
    scan(a,right,right['qr']['token'],'H2','H2-S1'); a.ack('ARRIVAL')
    student_status(a,'rights',right['id'],'CONSUMED')
    a.nav('alice','charging')
    session = a.submit('alice','register_charge',dict(right_id=right['id'],target_soc=80))
    event(a,'PLUG',session,'H2','H2-S1','H2-C1')
    student_status(a,'sessions',session['id'],'START_PENDING')
    a.check('Add charging requires no second arrival',sum(c['kind']=='ARRIVAL' and c['record_id']==right['id'] for c in a.rows('commands'))==1)


if __name__ == '__main__':
    for actor in ROLES:
        os.environ[f'EMOBILITY_{actor.upper()}_PASSWORD']=actor+'-demo'
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(channel='chrome',headless=True)
        for case in (charging,rental,parking_and_add):
            audit=Audit(browser,case.__name__)
            try:
                case(audit)
                audit.check('No browser JavaScript exceptions',not audit.page_errors,repr(audit.page_errors))
            except Exception as exc:
                audit.record('FAIL','Scenario aborted',str(exc)); traceback.print_exc()
            finally:
                audit.close()
        browser.close()
    summary=dict(Counter(row['status'] for row in RESULTS))
    Path(__file__).with_name('iot_ui_results.json').write_text(json.dumps({'summary':summary,'results':RESULTS},indent=2),encoding='utf-8')
    print('SUMMARY',summary)
    raise SystemExit(1 if summary.get('FAIL') else 0)
