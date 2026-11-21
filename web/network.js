'use strict';

const fleetSections = [
  {id:'network', label:'Network', roles:['operator'], view:networkStatus},
  {id:'transfers', label:'Transfers', roles:['operator','dispatcher'], view:transferDesk},
  {id:'tickets', label:'Maintenance', roles:['operator','technician'], view:maintenanceDesk},
  {id:'forecast', label:'Demand forecast', roles:['operator'], view:demandForecast},
  {id:'telemetry', label:'Telemetry', roles:['operator'], view:telemetryDesk}
];
let fleetSection = location.hash.slice(1).split('/')[1] || '';
let resourceHub = '';
let transferSource = '';

function fleetWorkspace() {
  const sections = fleetSections.filter(item => item.roles.includes(state.actor.role));
  const current = sections.find(item => item.id === fleetSection) || sections[0];
  return heading('D · Fleet operations', 'Fleet operations',
    {operator:'Monitor hub capacity, coordinate field staff and review vehicle observations.',
      dispatcher:'Collect your assigned vehicles and record their handover at the destination.',
      technician:'Review assigned maintenance tickets and record the outcome of each inspection.'}[state.actor.role]) +
    `<div id="fleet-workspace"><nav class="fleet-sections" aria-label="Fleet tools">${sections.map(item =>
      `<button class="${current === item ? '' : 'secondary'} small" data-fleet-section="${item.id}" ${current === item ? 'aria-current="page"' : ''}>${item.label}</button>`).join('')}</nav>${current.view()}</div>`;
}

const fleetResources = () => [
  ...list('ports').map(item => ({...item, type:'Charging port'})),
  ...list('spots').map(item => ({...item, type:'Parking bay'})),
  ...list('vehicles').map(item => ({...item, type:'Vehicle'}))
];

function networkStatus() {
  const resources = fleetResources();
  const selected = resourceHub || list('hubs')[0]?.id || '';
  const filtered = selected === 'all' ? resources : resources.filter(r=>r.hub_id===selected);
  return `<div class="grid">${list('hubs').map(h => {
    const stale = resources.filter(r => r.hub_id === h.id && r.freshness !== 'FRESH').length;
    return `<article class="record"><div class="record-main"><h2>${esc(h.name)}</h2>${chip(h.level)}</div>
      <div class="record-meta"><span>${h.available} of ${h.capacity} bays available</span><span>${h.effective_percent}% committed</span></div>
      <p class="small-text">${stale ? esc(stale)+' resources awaiting fresh observations' : 'Resource observations are current'}</p>
      <button class="link spaced" data-resource-hub="${esc(h.id)}">Inspect resources →</button></article>`;
  }).join('')}</div>
  <div class="section-heading"><h2>Resources</h2><label>Location<select data-resource-filter>${option('all','All locations',selected==='all')}${list('hubs').map(h=>option(h.id,h.name,h.id===selected)).join('')}</select></label></div>
  <div class="table-wrap"><table><thead><tr><th>Resource</th><th>Location</th><th>Condition</th><th>Observation</th><th>Availability control</th></tr></thead><tbody>${filtered.map(r=>
    `<tr><td><strong>${esc(r.id)}</strong><br>${esc(r.type)}</td><td>${esc(hubName(r.hub_id))}</td><td>${chip(r.health)}</td><td>${chip(r.freshness)}<br>${date(r.observed_at)}</td><td>${['OPERABLE','DEACTIVATED'].includes(r.health) && !r.maintenance_ticket_id ?
      actionButton(r.health==='DEACTIVATED'?'Reactivate':'Deactivate','d_resource_state',{resource_id:r.id,active:r.health==='DEACTIVATED'},'secondary small') : 'Under maintenance'}</td></tr>`
  ).join('')}</tbody></table></div>`;
}

function vehicleChecks(ids, labelFor) {
  return ids.map(id => `<label class="check-label"><input name="vehicle_ids" type="checkbox" value="${esc(id)}">${esc(labelFor(id))}</label>`).join('');
}

function transferFields() {
  const source = transferSource || list('hubs')[0]?.id;
  const vehicles = list('vehicles').filter(v => v.hub_id === source && v.kind === 'shared' && v.transferable);
  const destinations = list('hubs').filter(h => h.id !== source);
  return `<div class="form-row"><label>Source hub<select name="source_hub_id" data-transfer-source required>${list('hubs').map(h=>option(h.id,h.name,h.id===source)).join('')}</select></label>
    <label>Destination hub<select name="dest_hub_id" required>${destinations.map(h=>option(h.id,h.name)).join('')}</select></label></div>
    <fieldset class="vehicle-checks"><legend>Available shared vehicles</legend>${vehicles.length ? vehicleChecks(vehicles.map(v=>v.id),id=>id) : '<p class="muted">No eligible vehicle at this hub.</p>'}</fieldset>
    <label class="check-label"><input type="checkbox" name="charging_bays">Reserve charging bays at the destination</label>
    <label>Assigned staff<select name="staff_id">${option('dispatcher','Dispatcher')}</select></label>
    <button type="submit" ${vehicles.length && destinations.length ? '' : 'disabled'}>Preview transfer</button>`;
}

function transferOrder(order) {
  const operator = state.actor.role === 'operator';
  const delivered = order.delivered;
  const pendingIds = order.pending;
  const remaining = order.vehicle_ids.filter(id=>!delivered.includes(id) && !pendingIds.includes(id));
  let controls = '';
  if (operator && order.status === 'DRAFT') {
    controls = actionButton('Issue transfer','transfer_issue',{order_id:order.id},'small');
  } else if (!operator && order.status === 'ISSUED') {
    controls = actionButton('Start transfer','transfer_start',{order_id:order.id},'small');
  } else if (!operator && order.status === 'IN_PROGRESS' && remaining.length) {
    controls = `<form class="form" data-command="transfer_handover"><input type="hidden" name="order_id" value="${esc(order.id)}">
      <fieldset class="vehicle-checks"><legend>Vehicles presented at destination</legend>${vehicleChecks(remaining,id=>id)}</fieldset><button type="submit">Request handover</button></form>`;
  }
  return `<article class="record"><div class="record-main"><div><h3>${esc(hubName(order.source_hub_id))} → ${esc(hubName(order.dest_hub_id))}</h3><span class="record-id">${esc(order.id)}</span></div>${chip(order.status)}</div>
    <div class="record-meta"><span>Assigned to ${esc(order.staff_id)}</span><span>${delivered.length} / ${order.vehicle_ids.length} delivered</span></div>
    <p class="small-text">Vehicles · ${esc(order.vehicle_ids.join(', '))}${order.charging_bays?' · Charging bays requested':''}</p>
    ${delivered.length ? `<p class="small-text">Delivered · ${esc(delivered.join(', '))}</p>` : ''}
    ${pendingIds.length ? `<p class="record-note">Awaiting evidence · ${esc(pendingIds.join(', '))}${operator?' <button class="link" data-tab="operations">Open device outbox →</button>':''}</p>` : ''}
    ${controls ? `<div class="record-actions">${controls}</div>` : ''}</article>`;
}

function transferDesk() {
  const operator = state.actor.role === 'operator';
  const orders = list('orders').slice().reverse();
  const listing = `<section><div class="section-heading"><h2>${operator ? 'Transfer orders' : 'Assigned transfers'}</h2></div><div class="records">${orders.length ?
    orders.map(transferOrder).join('') : empty('No transfer orders',operator?'Preview a transfer to create a draft.':'Issued orders assigned to you appear here.')}</div></section>`;
  if (!operator) return listing;
  return `<div class="split">${listing}<section class="card"><div class="card-body"><h2>Plan a transfer</h2><form class="form spaced" data-command="transfer_preview">${transferFields()}</form></div></section></div>`;
}

function maintenanceTicket(ticket) {
  const isAssigned = state.actor.role === 'technician' && ticket.technician_id === state.actor.id;
  return `<article class="record"><div class="record-main"><div><h3>${esc(ticket.resource_id)}</h3><span class="record-id">${esc(ticket.id)}</span></div>${chip(ticket.status)}</div>
    <p class="spaced">${esc(ticket.message)}</p><div class="record-meta"><span>Assigned to ${esc(ticket.technician_id)}</span>${ticket.origin_incident_id?`<span>Source report · ${esc(ticket.origin_incident_id)}</span>`:''}</div>
    ${ticket.response?`<p class="record-note">${esc(ticket.response)}</p>`:''}
    ${isAssigned && ticket.status==='OPEN' ? `<form class="form spaced" data-command="d_update_incident">
      <input type="hidden" name="incident_id" value="${esc(ticket.id)}">
      <label>Inspection outcome<select name="outcome"><option value="ESCALATED_WORKSHOP">Escalate to workshop</option><option value="RESOLVED">Resolve and restore service</option></select></label>
      <label>Inspection notes<textarea name="note" required minlength="5" maxlength="1000"></textarea></label>
      <label class="check-label" hidden><input type="checkbox" name="safety_passed">I completed the safety checks and the resource passed.</label>
      <button type="submit">Record outcome</button></form>` : ''}</article>`;
}

function maintenanceDesk() {
  const incidents = list('incidents');
  const tickets = incidents.filter(row=>row.kind==='MAINTENANCE').slice().reverse();
  const listing = `<section><div class="section-heading"><h2>Maintenance tickets</h2></div><div class="records">${tickets.length ? tickets.map(maintenanceTicket).join('') : empty('No maintenance tickets')}</div></section>`;
  if (state.actor.role !== 'operator') return listing;
  const resources = fleetResources().filter(r=>!r.maintenance_ticket_id);
  const reports = incidents.filter(i=>i.kind!=='MAINTENANCE' && ['OPEN','WAITING_FOR_D'].includes(i.status) && !i.maintenance_ticket_id);
  return `<div class="split">${listing}<section class="card"><div class="card-body"><h2>Open a ticket</h2>
    <p class="muted small-text spaced">Opening a ticket isolates the resource and assigns it to the technician.</p><form class="form spaced" data-command="d_open_incident">
    <label>Affected resource<select name="resource_id" required>${option('','Select a resource')}${resources.map(r=>option(r.id,`${r.id} · ${r.type}`)).join('')}</select></label>
    <label>Source report (optional)<select name="origin_incident_id">${option('','Direct inspection')}${reports.map(i=>option(i.id,`${i.id} · ${i.message}`)).join('')}</select></label>
    <label>Issue description<textarea name="message" required minlength="5" maxlength="1000"></textarea></label><button type="submit">Open maintenance ticket</button></form></div></section></div>`;
}

function demandForecast() {
  const scenarios = list('scenarios').slice().reverse();
  return `<div class="split"><section><div class="section-heading"><h2>Demand scenarios</h2></div><div class="records">${scenarios.length ? scenarios.map(s => `<article class="record"><h3>${esc(hubName(s.hub_id))} · ${esc(s.demand_factor)}× demand</h3><span class="record-id">${esc(s.id)}</span>
    <div class="table-wrap spaced"><table><thead><tr><th>Hub</th><th>Current load</th><th>Projected load</th></tr></thead><tbody>${s.impact.map(h=>`<tr><td>${esc(hubName(h.hub_id))}</td><td>${esc(h.current_percent)}%</td><td>${esc(h.projected_percent)}%</td></tr>`).join('')}</tbody></table></div>
    ${s.recommendations.length ? s.recommendations.map((r,i)=>`<div class="record-note"><p>${esc(hubName(r.source_hub_id))} → ${esc(hubName(r.dest_hub_id))} · ${esc(r.vehicle_ids.join(', '))}</p><div class="record-actions">${actionButton('Create transfer draft','what_if_draft',{scenario_id:s.id,recommendation_index:i},'secondary small')}</div></div>`).join('') : '<p class="record-note">No transfers recommended for this scenario.</p>'}</article>`).join('') : empty('No forecasts yet')}</div></section>
    <section class="card"><div class="card-body"><h2>Model a change in demand</h2><form class="form spaced" data-command="what_if">
      <label>Target hub<select name="hub_id" required>${hubOptions()}</select></label><label>Demand multiplier<input type="number" min="0.5" max="3" step="0.1" name="demand_factor" value="1.5" required></label><button type="submit">Run forecast</button>
      <p class="form-help">Review the projected load before creating any transfer orders.</p></form></div></section></div>`;
}

function telemetryRows(vehicles) {
  const packets = vehicles.map(v=>v.last_telemetry).filter(Boolean).sort((a,b)=>b.observed_at-a.observed_at);
  return packets.length ? `<div class="records">${packets.map(p=>`<article class="record"><div class="record-main"><h3>${esc(p.resourceId)}</h3>${chip('SIMULATED')}</div>
    <div class="record-meta"><span>${date(p.observed_at)}</span><span>Packet ${esc(p.sequence)}</span></div>
    <p>${esc(p.batterySoc)}% battery${p.speed!=null?' · '+esc(p.speed)+' km/h':''}${p.temperatureC!=null?' · '+esc(p.temperatureC)+' °C':''}</p>
    ${p.destinationHubId?`<p class="small-text">Destination · ${esc(hubName(p.destinationHubId))}</p>`:''}
    ${p.alerts?.length?`<div class="record-note">${esc(p.alerts.map(title).join(' · '))}</div>`:''}</article>`).join('')}</div>` : empty('No vehicle readings received');
}

function telemetryDesk() {
  const vehicles = list('vehicles');
  const listing = `<section><div class="section-heading"><h2>Latest vehicle readings</h2>
    <label class="check-label"><input type="checkbox" id="live-telemetry" checked>Live updates</label></div>
    <div id="telemetry-readings">${telemetryRows(vehicles)}</div></section>`;
  if (!state.simulator) return listing;
  return `<div class="split">${listing}<section class="sim-area"><h2>Simulate a vehicle reading</h2>
    <form class="form spaced" data-command="d_telemetry"><label>Vehicle<select name="resourceId" required>${vehicles.map(v=>option(v.id,v.id)).join('')}</select></label>
    <label>Battery charge (%)<input type="number" min="0" max="100" step="0.1" name="batterySoc" value="65" required></label>
    <div class="form-row"><label>Speed (km/h)<input type="number" min="0" step="0.1" max="500" name="speed" value="0"></label><label>Temperature (°C)<input type="number" step="0.1" min="-80" max="250" name="temperatureC" value="27"></label></div>
    <label>Destination (optional)<select name="destinationHubId">${option('','No destination')}${list('hubs').map(h=>option(h.id,h.name)).join('')}</select></label>
    <button type="submit">Send simulated reading</button></form></section></div>`;
}

function prepareFleetCommand(form, values, payload) {
  if (form.elements.vehicle_ids) {
    payload.vehicle_ids = values.getAll('vehicle_ids');
    if (!payload.vehicle_ids.length) {
      showNotice('Select at least one vehicle for this transfer.', true);
      return false;
    }
  }
  if (form.elements.charging_bays) payload.charging_bays = form.elements.charging_bays.checked;
  if (form.elements.safety_passed) payload.safety_passed = form.elements.safety_passed.checked;
  for (const field of ['demand_factor','batterySoc','speed','temperatureC']) {
    if (payload[field] !== undefined && payload[field] !== '') payload[field] = Number(payload[field]);
  }
  for (const field of ['origin_incident_id','destinationHubId','speed','temperatureC']) {
    if (payload[field] === '') delete payload[field];
  }
  if (form.dataset.command === 'd_telemetry') payload.event_id = crypto.randomUUID();
  return true;
}

document.addEventListener('click', event => {
  const target = event.target.closest('#fleet-workspace button');
  if (!target) return;
  if (target.dataset.fleetSection) {
    fleetSection = target.dataset.fleetSection;
    window.history.replaceState(null,'','#network/'+fleetSection);
    render();
  } else if (target.dataset.resourceHub) {
    resourceHub = target.dataset.resourceHub;
    render();
    document.querySelector('[data-resource-filter]')?.focus();
  }
});

document.addEventListener('change', event => {
  const input = event.target;
  if (!input.closest('#fleet-workspace')) return;
  if (input.matches('[data-resource-filter]')) {
    resourceHub = input.value;
    render();
    document.querySelector('[data-resource-filter]')?.focus();
  } else if (input.matches('[data-transfer-source]')) {
    transferSource = input.value;
    input.form.innerHTML = transferFields();
    document.querySelector('[data-transfer-source]')?.focus();
  } else if (input.name === 'outcome') {
    const check = input.form.elements.safety_passed;
    check.required = input.value === 'RESOLVED';
    check.closest('label').hidden = !check.required;
    if (!check.required) check.checked = false;
  }
});


// Update the packet list in place so an operator can finish entering a reading.
let readingTelemetry = false;
setInterval(async () => {
  const panel = document.getElementById('telemetry-readings');
  if (!panel || document.hidden || !document.getElementById('live-telemetry')?.checked || busy || readingTelemetry) return;
  readingTelemetry = true;
  try {
    const snapshot = await request('/api/state');
    if (panel.isConnected && !busy && snapshot.actor.role === 'operator') {
      panel.innerHTML = telemetryRows(snapshot.vehicles);
    }
  } catch (error) {
    if (panel.isConnected) {
      document.getElementById('live-telemetry').checked = false;
      if (error.status === 401) {state = null; renderLogin();}
      else showNotice('Live readings paused. ' + error.message, true);
    }
  } finally {
    readingTelemetry = false;
  }
}, 5000);
