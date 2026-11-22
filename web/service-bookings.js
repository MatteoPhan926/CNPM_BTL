'use strict';

function compatibleChargingRights() {
  return list('rights').filter(r=>{
    if (!['CONFIRMED','CONSUMED'].includes(r.status)||r.end<=now()) return false;
    if (r.status==='CONSUMED'&&!list('visits').some(v=>v.right_id===r.id&&v.status==='PARKED')) return false;
    const vehicle=find('vehicles',r.vehicle_id);
    if (!vehicle||vehicle.owner_id!==state.actor.id) return false;
    if (list('sessions').some(s=>s.vehicle_id===r.vehicle_id&&['BOOKED','START_PENDING','CHARGING','STOP_PENDING'].includes(s.status))) return false;
    return list('ports').some(p=>p.spot_id===r.spot_id&&p.connector===vehicle.connector&&p.health==='OPERABLE');
  });
}

function chargingRequestForm() {
  if (state.actor.role !== 'student') return '';
  return `<section class="card"><div class="card-body"><div class="eyebrow">Charging only</div><h2>Book a charging bay</h2>
    <p class="muted small-text spaced">No parking reservation needed. The system proposes a compatible bay and charging time for operator review.</p>
    <form class="form spaced" data-command="submit_charge_request">
      <label>Vehicle<select name="vehicle_id" required>${option('','Choose your personal vehicle')}${myVehicles().filter(v=>v.kind==='personal').map(v=>option(v.id,vehicleName(v.id))).join('')}</select></label>
      <label>Hub<select name="hub_id" required>${hubOptions()}</select></label>
      <label>Current battery SOC (%)<input name="declared_soc" type="number" min="0" max="99" step="1" value="30" required></label>
      <label>Desired battery SOC (%)<input name="target_soc" type="number" min="1" max="100" step="1" value="80" required></label>
      <label>Arrival time<input name="arrival_time" type="datetime-local" required value="${inputDate(now()+120)}"></label>
      <button type="submit">Reserve charging</button>
      <p class="form-help">Battery level is your declaration, not a device reading. A confirmation QR becomes available after operator approval. Arrival and charging still require external evidence.</p>
    </form></div></section>`;
}

function chargingRequestCards(operator=false) {
  const requests=list('charge_requests').slice().reverse();
  return `<section class="spaced"><div class="section-heading"><h2>${operator?'Charging requests · operator review':'Charging-only reservations'}</h2></div><div class="records">${requests.length?requests.map(r=>{
    const proposal=r.session_id?r:(r.proposal||r);
    const vehicle=find('vehicles',r.vehicle_id);
    return `<article class="record"><div class="record-main"><div><div class="record-title"><h3>${esc(vehicleName(r.vehicle_id))}</h3><span class="record-id">${esc(r.id)}</span></div><div class="record-meta"><span>${esc(hubName(r.hub_id))}</span><span>Declared ${esc(r.declared_soc)}% → target ${esc(r.target_soc)}%</span>${operator?`<span>Requested by ${esc(r.owner_id)}</span>`:''}</div></div>${chip(r.status)}</div>
      <p class="muted small-text spaced">Reservation type: Charging only · Arrival ${date(r.arrival_time)}</p>
      ${operator?`<p class="muted small-text">Battery ${esc(r.battery_kwh??vehicle?.battery_kwh)} kWh · Connector ${esc(r.connector||vehicle?.connector)}</p>`:''}
      ${proposal.port_id?`<div class="record-note"><strong>${r.status==='PENDING'?'Automatic proposal':'Allocation'}</strong><p>Bay ${esc(proposal.spot_id)} · Port ${esc(proposal.port_id)}</p><p>Energy required: ${esc(Number(proposal.energy_kwh).toFixed(2))} kWh · Allocated power: ${esc(proposal.kw)} kW</p><p>Scheduled start: ${date(proposal.scheduled_start)}</p><p>Estimated charging end: ${date(proposal.scheduled_end)} · Estimated duration: ${esc(Math.ceil(proposal.duration/60))} minutes</p><p>Expected collection: ${date(proposal.expected_collection_at)}</p><p>Estimates use your declared SOC and 90% efficiency; actual battery level and completion time require device evidence.</p></div>`:''}
      ${proposal.available===false?`<p class="record-note">Proposal unavailable: ${esc(proposal.reason)}</p>`:''}
      ${r.rejection_reason?`<p class="record-note">Rejection reason: ${esc(r.rejection_reason)}</p>`:''}
      ${r.status==='COMPLETED'?'<p class="record-note">Charging has stopped. Please collect your vehicle: unplug and leave the bay. The bay remains occupied until departure is confirmed.</p>':''}
      ${r.status==='PENDING'?'<p class="muted small-text spaced">Awaiting operator confirmation. Proposed resources are rechecked at approval.</p>':''}
      <div class="record-actions">${!operator&&r.status==='BOOKED'?`<button class="secondary small" data-service-qr="charging" data-id="${esc(r.id)}">Show charging QR</button>`:''}${!operator&&['PENDING','BOOKED'].includes(r.status)?actionButton('Cancel charging reservation','cancel_charge_request',{request_id:r.id},'danger small'):''}${operator&&r.status==='PENDING'?actionButton('Confirm charging proposal','approve_charge_request',{request_id:r.id},'small'):''}</div>
      ${operator&&r.status==='PENDING'?`<form class="form spaced" data-command="reject_charge_request"><input type="hidden" name="request_id" value="${esc(r.id)}"><label>Rejection reason<input name="reason" required minlength="5" maxlength="500" placeholder="Explain why this request cannot be confirmed"></label><button type="submit" class="danger small">Reject charging request</button></form>`:''}</article>`;
  }).join(''):empty('No charging-only requests',operator?'New requests will appear here for review.':'Submit a charging request to receive an operator-confirmed allocation.')}</div></section>`;
}

function rentalQrButton(hold) {
  return hold.owner_id===state.actor.id&&hold.qr?`<button class="secondary small" data-service-qr="rental" data-id="${esc(hold.id)}">Show rental QR</button>`:'';
}

const serviceQrDialog=document.querySelector('#service-qr-dialog');
let serviceQrSelection=null, serviceQrVersion=0, serviceQrTimer;
function clearServiceQr() {
  serviceQrVersion++;
  serviceQrSelection=null;
  clearTimeout(serviceQrTimer);
  renderQrContents('#service-qr-content','');
  document.querySelector('#service-qr-feedback').hidden=true;
}
async function loadServiceQr() {
  if (!serviceQrDialog.open||!serviceQrSelection||!state) return;
  const {kind,id}=serviceQrSelection, version=++serviceQrVersion, actor=state.actor.id;
  clearTimeout(serviceQrTimer);
  try {
    const qr=await request(`/api/${kind}-qr?${kind==='rental'?'hold_id':'request_id'}=${encodeURIComponent(id)}`);
    if (version!==serviceQrVersion||!serviceQrDialog.open||actor!==state?.actor.id) return;
    const record=find(kind==='rental'?'holds':'charge_requests',id);
    const right=kind==='charging'?find('rights',record?.right_id):null;
    renderQrContents('#service-qr-content',`<div class="eyebrow">${esc(title(kind))} confirmation</div><h2 id="service-qr-title">Your ${esc(kind)} QR</h2>
      <p class="spaced">${chip(qr.status)} ${esc(qr.message)}</p>
      ${qr.svg?`<img class="parking-qr-image" alt="${esc(title(kind))} reservation QR code" src="data:image/svg+xml;charset=utf-8,${encodeURIComponent(qr.svg)}">`:''}
      <dl class="parking-qr-details"><dt>Reservation ID</dt><dd>${esc(id)}</dd><dt>Vehicle</dt><dd>${esc(vehicleName(record?.vehicle_id))}</dd><dt>Hub</dt><dd>${esc(hubName(record?.hub_id||record?.pickup_hub_id))}</dd>
      ${right?`<dt>Charging bay</dt><dd>${esc(right.spot_id)}</dd><dt>Port</dt><dd>${esc(record.port_id)}</dd><dt>Charging window</dt><dd>${date(record.scheduled_start)} → ${date(record.scheduled_end)}</dd>`:''}
      <dt>Code valid until</dt><dd>${date(qr.expires_at)}</dd></dl>
      <label>Confirmation code<input readonly value="${esc(qr.token)}"></label>
      <p class="muted small-text spaced">Present this QR code at the assigned Hub or parking bay. Your reservation status will update automatically after verification.</p>`);
    serviceQrTimer=setTimeout(loadServiceQr,5000);
  } catch(error) {
    if(version!==serviceQrVersion||!serviceQrDialog.open) return;
    renderQrContents('#service-qr-content',`<h2 id="service-qr-title">QR unavailable</h2><p class="spaced">${esc(error.message)}</p>`);
  }
}
async function showServiceQr(kind,id) {
  serviceQrSelection={kind,id};
  document.querySelector('#service-qr-feedback').hidden=true;
  renderQrContents('#service-qr-content','<h2 id="service-qr-title">Loading confirmation QR…</h2>');
  if(!serviceQrDialog.open) serviceQrDialog.showModal();
  await loadServiceQr();
}
serviceQrDialog.addEventListener('close',clearServiceQr);
document.querySelector('#close-service-qr').addEventListener('click',()=>serviceQrDialog.close());

function formDraftKey(form) {
  return form.id||`${form.dataset.command}:${Array.from(form.querySelectorAll('input[type=hidden]')).map(el=>el.name+'='+el.value).join(',')}`;
}
function captureFormDrafts() {
  const active=document.activeElement;
  return Array.from(app.querySelectorAll('form')).filter(form=>form.dataset.dirty==='true'||form.contains(active)).map(form=>({
    key:formDraftKey(form),dirty:form.dataset.dirty,
    fields:Array.from(form.elements).filter(el=>el.name).map(el=>({name:el.name,value:el.value,checked:el.checked})),
    focus:form.contains(active)?active.name:null,
    selection:form.contains(active)&&typeof active.selectionStart==='number'?[active.selectionStart,active.selectionEnd]:null,
  }));
}
function restoreFormDrafts(drafts) {
  for(const draft of drafts) {
    const form=Array.from(app.querySelectorAll('form')).find(item=>formDraftKey(item)===draft.key);
    if(!form) continue;
    if(draft.dirty) form.dataset.dirty=draft.dirty;
    for(const field of draft.fields) {
      const el=form.elements.namedItem(field.name);
      if(!el) continue;
      if(el.tagName!=='SELECT'||Array.from(el.options).some(o=>o.value===field.value)) el.value=field.value;
      if(el.type==='checkbox'||el.type==='radio') el.checked=field.checked;
    }
    const focus=draft.focus?form.elements.namedItem(draft.focus):null;
    if(focus) {focus.focus({preventScroll:true});if(draft.selection) focus.setSelectionRange(...draft.selection);}
  }
}
function notifyServiceTransitions(previous,next) {
  if(next.actor.role!=='student'||pending()) return;
  const changes=[];
  for(const key of ['holds','trips','rights','visits','sessions','charge_requests']) {
    const old=new Map((previous[key]||[]).map(record=>[record.id,record.status]));
    for(const record of next[key]||[]) if(old.has(record.id)&&old.get(record.id)!==record.status) changes.push(`${record.id}: ${title(record.status)}`);
  }
  if(changes.length) showNotice(`Service update — ${changes.slice(0,3).join('; ')}${changes.length>3?' …':''}`);
}

function technicalSimulator() {
  if(state.actor.role!=='operator'||!state.simulator) return empty('Simulator unavailable');
  const records=[...list('trips'),...list('sessions'),...list('visits')];
  return heading('Technical simulation only','Device event simulator','Synthetic events exercise the Role D boundary. No physical device is contacted.')+
    `<div class="grid two"><section class="card"><div class="card-body"><h2>Simulate a QR reader</h2><p class="muted small-text spaced">Enter the code presented by the student and the reader location. A valid scan creates a pending handover command. Deliver its synthetic ACK in Operations.</p>
    <form class="form spaced" data-command="sim_iot_scan"><label>QR token<input name="qr_token" required autocomplete="off" spellcheck="false"></label><label>Observed vehicle<select name="vehicle_id" required>${list('vehicles').map(v=>option(v.id,vehicleName(v.id))).join('')}</select></label><label>Reader Hub<select name="hub_id" required>${hubOptions()}</select></label><label>Reader bay<select name="spot_id" required>${list('spots').map(s=>option(s.id,`${s.id} · ${hubName(s.hub_id)}`)).join('')}</select></label><button type="submit">Simulate QR scan</button></form></div></section>
    <section class="card"><div class="card-body"><h2>Simulate physical evidence</h2><p class="muted small-text spaced">Prepare return allocates reception without claiming arrival. Other events submit explicit synthetic evidence for the selected record and location.</p>
    <form class="form spaced" data-command="sim_iot_event"><label>Event<select name="kind" required>${['PLUG','UNPLUG','DEPARTURE','RETURN_PREPARE','RETURN'].map(k=>option(k,title(k))).join('')}</select></label><label>Related record<select name="record_id" required>${option('','Choose a session, visit or trip')}${records.map(r=>option(r.id,`${r.id} · ${r.vehicle_id} · ${title(r.status)}`)).join('')}</select></label><label>Observed vehicle<select name="vehicle_id" required>${list('vehicles').map(v=>option(v.id,vehicleName(v.id))).join('')}</select></label><label>Observed Hub<select name="hub_id" required>${hubOptions()}</select></label><label>Observed bay (optional only for Prepare return)<select name="spot_id">${option('','No bay yet')}${list('spots').map(s=>option(s.id,`${s.id} · ${hubName(s.hub_id)}`)).join('')}</select></label><label>Charging port (plug / unplug)<select name="port_id">${option('','Not a charging event')}${list('ports').map(p=>option(p.id,`${p.id} · ${p.spot_id}`)).join('')}</select></label><button type="submit">Submit simulated event</button></form></div></section></div><button class="link spaced" data-tab="operations">Review pending device commands →</button>`;
}
