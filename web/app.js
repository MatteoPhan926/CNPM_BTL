'use strict';

const app = document.querySelector('#app');
const notice = document.querySelector('#notice');
let state = null;
let tab = location.hash.slice(1).split('/')[0] || 'overview';
let selectedHub = '';
let busy = false;
let noticeTimer;
let noticeExitTimer;
let refreshVersion = 0;
let lastNotifiedPending = null;
const tabs = [
  ['overview', '◈', 'Explore hubs'], ['journeys', '↗', 'My journeys'],
  ['parking', '▦', 'Parking'], ['charging', 'ϟ', 'Charging'],
  ['support', '◎', 'Support'], ['operations', '≋', 'Operations'],
  ['technical', 'T', 'Technical simulator'], ['network', '⇄', 'Fleet operations'], ['history', '◷', 'Activity']
];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const list = key => Array.isArray(state?.[key]) ? state[key] : [];
const find = (key, id) => list(key).find(row => row.id === id);
const title = value => String(value || '').replaceAll('_', ' ').toLowerCase().replace(/^./, c => c.toUpperCase());
const date = value => value ? new Date(value * 1000).toLocaleString([], {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'}) : '—';
const inputDate = value => { const d = new Date(value * 1000); return new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0,16); };
const now = () => state?.now || Date.now()/1000;
const hubName = id => find('hubs', id)?.name || id || 'In transit';
const vehicleName = id => {const v = find('vehicles', id); return v ? `${v.label || v.id} · ${v.kind === 'shared' ? 'Shared' : 'Personal'}` : id;};
const statusClass = status => /PENDING|UNKNOWN|STALE|WARNING|RESERVED|BOOKED|PROPOSED|WAIT|DRAFT|ASSISTANCE/i.test(status) ? 'warn' : /FAULT|REJECT|OUT_OF_SERVICE|EXPIRED|CANCEL|CLOSED_UNFULFILLED/i.test(status) ? 'bad' : /ACTIVE|AVAILABLE|CONFIRM|OPEN|CLOSED|COMPLETED|ACK|APPLIED|OPERABLE|EMPTY|UNPLUGGED/i.test(status) ? 'good' : 'neutral';
const chip = status => `<span class="chip ${statusClass(status)}">${esc(title(status))}</span>`;
const actionButton = (label, action, payload, style='secondary small') => `<button class="${style}" data-action="${esc(action)}" data-payload="${esc(JSON.stringify(payload))}">${esc(label)}</button>`;
const option = (value, label, selected=false) => `<option value="${esc(value)}" ${selected?'selected':''}>${esc(label)}</option>`;
const empty = (heading, text='') => `<div class="empty"><strong>${esc(heading)}</strong>${esc(text)}</div>`;
const pendingKey = () => `emobility_pending_${state?.actor?.id}`;
const pending = () => {try{return JSON.parse(localStorage.getItem(pendingKey()) || 'null');}catch{return null;}};

async function request(path, data) {
  const response = await fetch(path, {method:data === undefined?'GET':'POST', credentials:'same-origin', headers:data === undefined?{}:{'Content-Type':'application/json'}, body:data === undefined?undefined:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) {const error = new Error(result.error?.message || 'Request failed.'); error.code=result.error?.code; error.status=response.status; throw error;}
  return result;
}

function showNotice(message, error = false, retry = false) {
    clearTimeout(noticeTimer);
    clearTimeout(noticeExitTimer);

    const type = retry
        ? 'warning'
        : error
            ? 'error'
            : 'success';

    const config = {
        success: {
            icon: '✓',
            heading: 'Success'
        },
        error: {
            icon: '!',
            heading: 'Request failed'
        },
        warning: {
            icon: '!',
            heading: 'Confirmation required'
        }
    }[type];

    notice.className = `notice toast-${type}`;
    notice.hidden = false;

    notice.innerHTML = `
        <div class="toast-icon" aria-hidden="true">
            ${config.icon}
        </div>

        <div class="toast-content">
            <strong class="toast-title">
                ${config.heading}
            </strong>

            <span class="toast-message">
                ${esc(message)}
            </span>
        </div>

        <button
            type="button"
            class="${retry ? 'toast-retry' : 'toast-close'}"
            data-notice="${retry ? 'retry' : 'close'}"
            aria-label="${retry ? 'Retry same request' : 'Dismiss'}"
        >
            ${retry ? 'Retry' : '×'}
        </button>

        <div class="toast-progress"></div>
    `;

    const duration = retry
        ? 10000
        : error
            ? 6000
            : 4000;

    notice.style.setProperty(
        '--toast-duration',
        `${duration}ms`
    );

    void notice.offsetWidth;

    notice.classList.add('toast-enter');

    noticeTimer = setTimeout(() => {
        hideNotice();
    }, duration);
}

function hideNotice(immediate = false) {
    clearTimeout(noticeTimer);
    clearTimeout(noticeExitTimer);

    notice.classList.remove('toast-enter');

    if (immediate === true) {
        notice.hidden = true;
        notice.classList.remove('toast-exit');
        return;
    }

    if (notice.hidden) return;

    notice.classList.add('toast-exit');

    noticeExitTimer = setTimeout(() => {
        notice.hidden = true;
        notice.classList.remove('toast-exit');
    }, 250);
}

async function refresh(renderView=true, background=false) {
  const version=++refreshVersion;
  try {
    const next=await request('/api/state');
    if (version!==refreshVersion) return false;
    const previous=state;
    const changed=JSON.stringify({...previous,now:0})!==JSON.stringify({...next,now:0});
    state=next;
    if (renderView&&(!background||changed)) {
      const drafts=background?captureFormDrafts():null;
      render();
      if(drafts) restoreFormDrafts(drafts);
    }
    if(background&&previous) notifyServiceTransitions(previous,next);
    if (parkingQrDialog.open) await loadParkingQr();
    if (serviceQrDialog.open) await loadServiceQr();
    return true;
  } catch (error) {
    if(version!==refreshVersion) return false;
    if (error.status === 401) {state=null;renderLogin();}
    else showNotice(`Unable to refresh: ${error.message}`, true);
    return false;
  }
}

async function command(action, payload, retry=false) {
  if (busy) return;
  const saved = pending();
  if (saved && !retry) {
    const message = 'A previous request has an uncertain outcome. Recover it before submitting another change.';
    showNotice(message, true, true);
    return {error:message, retry:true};
  }
  const envelope = retry ? saved : {action, payload, intent_id:crypto.randomUUID()};
  if (!envelope) return;
  busy = true;
  refreshVersion++;
  localStorage.setItem(pendingKey(), JSON.stringify(envelope));
  const locks = document.querySelectorAll('button[data-action]:enabled, form button[type=submit]:enabled, #logout');
  locks.forEach(button=>button.disabled=true);
  try {
    const result = await request('/api/commands', envelope);
    localStorage.removeItem(pendingKey());
    await refresh();
    const outcome = result.record?.status || result.status;
    if (outcome === 'ANOMALY' || outcome === 'REJECTED') {
      showNotice(`${title(outcome)}. ${result.record.reason || 'Review the command and resource state in the device outbox.'}`, true);
    } else if (result.status === 'PENDING_VERIFICATION') {
      showNotice('Request recorded. Awaiting handover or device evidence.');
    } else {
      showNotice(`${title(outcome || 'Saved')}. Your records are updated.`);
    }
  } catch (error) {
    if (error.status && error.status < 500) {
      localStorage.removeItem(pendingKey());
      if (error.status === 401) {state=null;renderLogin();}
      showNotice(`${error.code ? title(error.code)+': ' : ''}${error.message}`, true);
    } else showNotice('The response was lost or the server could not confirm the outcome. Retry the same request to recover its recorded result.', true, true);
    return {error:notice.querySelector('span').textContent, retry:!error.status || error.status >= 500};
  } finally {
    busy=false;
    locks.forEach(button=>button.disabled=false);
  }
}

function renderLogin() {
  refreshVersion++;
  if (parkingQrDialog.open) parkingQrDialog.close();
  if (serviceQrDialog.open) serviceQrDialog.close();
  app.innerHTML = `<div class="login-shell"><section class="login-story"><div class="brand"><img class="brand-symbol" src="/icons/brand.svg" alt=""><div><strong>Smart E-Mobility</strong><small>VNU–HCM MOBILITY NETWORK</small></div></div><div><div class="eyebrow">A better way across campus</div><h1>Your next journey.<br>A little greener.</h1><p>Find a shared vehicle, reserve a place to park, and manage your charging in one connected workspace.</p></div><div class="login-story-footer">Campus mobility services · Local demonstration</div></section><main class="login-panel" id="main"><div class="login-card"><div class="eyebrow">Welcome to the hub</div><h2>Sign in to get moving</h2><p class="muted">Use a local demo account to explore the working journeys.</p><form id="login-form" class="form"><label>Username<input name="username" autocomplete="username" required value="alice"></label><label>Password<input name="password" type="password" autocomplete="current-password" required value="alice-demo"></label><button type="submit">Sign in →</button><p class="login-error" id="login-error" role="alert"></p></form><div class="demo-note"><strong>Local demo accounts</strong><p><code>alice / alice-demo</code><br><code>bob / bob-demo</code><br><code>operator / operator-demo</code><br><code>dispatcher / dispatcher-demo</code><br><code>technician / technician-demo</code></p><p>Passwords may be overridden by the server environment. Staff accounts open the fleet workspace. The simulator is enabled separately at server startup.</p></div></div></main></div>`;
  if (location.hostname.endsWith('.onrender.com')) {
    const input = app.querySelector('input[name="password"]');
    if (input) input.value = '';
    const notice = app.querySelector('.demo-note');
    if (notice) notice.innerHTML = '<strong>Private academic demo</strong><p>Sign in with the temporary credentials shared by the project administrator. Device actions are simulated and data may reset on free hosting.</p>';
  }
}

function render() {
  if (!state) return renderLogin();
  const operator = state.actor.role === 'operator';
  const staff = ['operator', 'dispatcher', 'technician'].includes(state.actor.role);
  const availableTabs = tabs.filter(([id]) => {
    if (id === 'technical') return operator && state.simulator;
    if (id === 'network') return staff;
    if (id === 'operations') return operator;
    if (staff && !operator) return ['overview', 'history'].includes(id);
    return true;
  });
  if (!availableTabs.some(([id]) => id === tab)) tab = staff ? 'network' : 'overview';
  const views = {overview, journeys, parking, charging, support, operations, history: activityHistory, network: fleetWorkspace, technical: technicalSimulator};
  app.innerHTML = `<div class="shell"><aside class="sidebar"><div class="brand"><img class="brand-symbol" src="/icons/brand.svg" alt=""><div class="brand-text"><strong>Smart<br>E-Mobility</strong><small>VNU–HCM NETWORK</small></div></div><div class="nav-label">YOUR WORKSPACE</div><nav class="nav" aria-label="Main navigation">${availableTabs.map(([id,icon,label])=>`<button data-tab="${id}" class="${tab===id?'active':''}" ${tab===id?'aria-current="page"':''} title="${label}" aria-label="${label}"><img class="icon" src="/icons/${id}.svg" alt=""><span class="nav-text">${label}</span></button>`).join('')}</nav><div class="sidebar-foot"><strong>Connected campus.<br>Considered journeys.</strong><p class="spaced">Rentals & journeys<br>Parking & capacity<br>Charging & schedules<br>Fleet operations</p><p class="spaced">Local MVP · ${esc(title(state.actor.role))} access</p></div></aside><div class="main-column"><header class="topbar"><div class="breadcrumb">VNU–HCM / Mobility services / <strong>${esc(tabs.find(row=>row[0]===tab)[2])}</strong></div><div class="account"><span class="avatar">${esc(state.actor.id[0].toUpperCase())}</span><div><strong>${esc(title(state.actor.id))}</strong><div class="small-text muted">${esc(title(state.actor.role))}</div></div><button class="secondary small" id="logout">Sign out</button></div></header><main class="content" id="main"><div class="mode-banner">${pending() ? `
    <div class="record-note spaced">
        <strong>Pending request</strong>
        <p>
            A previous request requires confirmation.
        </p>
        <button
            type="button"
            class="secondary small"
            id="recover-pending"
        >
            Recover request
        </button>
    </div>
` : ''}<strong>${state.simulator?'◇ Controlled simulation enabled':'◇ Device simulator offline'}</strong><span>${state.simulator?'All device evidence is synthetic. An operator must explicitly deliver each simulated outcome.':'Handover and charging requests stay pending until evidence arrives.'}</span></div>${views[tab]()}</main></div></div>`;
  const saved = pending();

  if (!saved) {
      lastNotifiedPending = null;
  } else {
      const pendingId =
          `${state.actor.id}:${saved.intent_id}`;

      if (lastNotifiedPending !== pendingId) {
          lastNotifiedPending = pendingId;

          showNotice(
              'A request has an uncertain outcome. Recover it using the same saved intent.',
              true,
              true
          );
      }
  }
}

function heading(kicker, name, description, extra='') {
  return `<div class="page-title"><div><div class="eyebrow">${esc(kicker)}</div><h1>${esc(name)}</h1><p>${esc(description)}</p></div><div class="toolbar"><button class="secondary small" id="refresh">↻ Refresh</button>${extra}</div></div>`;
}

function overview() {
  const hubs=list('hubs'), vehicles=list('vehicles').filter(v=>v.kind==='shared' && (!selectedHub||v.hub_id===selectedHub));
  return heading('Explore the network', 'Where are you heading?', 'Live resource snapshots, committed reservations and observed occupancy — together in one view.')+
    `<section class="stats" aria-label="Network summary"><div class="stat"><div class="label">Mobility hubs</div><div class="number">${hubs.length}</div><div class="hint">Metro · campus · dormitories</div></div><div class="stat"><div class="label">Available shared vehicles</div><div class="number">${list('vehicles').filter(v=>v.kind==='shared'&&v.available).length}</div><div class="hint">Fresh, eligible and unclaimed</div></div><div class="stat"><div class="label">Available parking spaces</div><div class="number">${hubs.reduce((n,h)=>n+(h.available||0),0)}</div><div class="hint">Subject to time and reception policy</div></div><div class="stat"><div class="label">Your active services</div><div class="number">${state.active_services}</div><div class="hint">Manage from your workspace</div></div></section>`+
    `<div class="section-heading"><h2>Find your hub</h2><span class="state-age">Updated ${esc(date(state.now))} · Revision ${esc(state.revision)}</span></div><div class="grid">${hubs.map((hub,i)=>`<article class="card hub-card"><div class="hub-art"><span>0${i+1} / ${esc(hub.name)}</span></div><div class="card-body"><div class="card-heading"><div><h3>${esc(hub.name)}</h3><p class="muted small-text">${esc(hub.id)} · ${esc(hub.power_kw)} kW charging budget</p></div>${chip(hub.level||'OPEN')}</div><div class="capacity"><div class="capacity-line"><span>Effective commitments</span><strong>${(hub.occupied||0)+(hub.unknown||0)+(hub.held||0)} / ${hub.capacity}</strong></div><progress class="meter ${hub.available<3?'warn':''}" max="${hub.capacity||1}" value="${(hub.occupied||0)+(hub.unknown||0)+(hub.held||0)}" aria-label="Effective parking commitments"></progress><div class="facts"><span>${hub.occupied||0} occupied</span><span>${hub.held||0} held</span><span>${hub.unknown||0} unknown</span></div></div><div class="card-footer"><span class="small-text muted">${list('vehicles').filter(v=>v.kind==='shared'&&v.hub_id===hub.id&&v.available).length} vehicles available</span><button class="link" data-hub="${esc(hub.id)}">View vehicles →</button></div></div></article>`).join('')}</div>`+
    `<div class="section-heading"><h2>Shared vehicles</h2><label class="visually-hidden" for="hub-filter">Filter by hub</label><select id="hub-filter" class="inline-input">${option('','All hubs',!selectedHub)}${hubs.map(h=>option(h.id,h.name,h.id===selectedHub)).join('')}</select></div>${vehicles.length?`<div class="table-wrap"><table><thead><tr><th>Vehicle</th><th>Location</th><th>Battery</th><th>Observation</th><th>Availability</th><th>Action</th></tr></thead><tbody>${vehicles.map(v=>`<tr><td class="vehicle-name">${esc(v.label||v.id)}</td><td>
    ${esc(hubName(v.hub_id))}
    <br>
    <span class="muted small-text">
        ${v.spot_id
            ? `Bay ${esc(v.spot_id)}`
            : 'No assigned bay'}
    </span>
</td><td><span class="battery">▰ ${esc(v.soc)}%</span></td><td>${chip(v.freshness||(now()-v.observed_at>90?'STALE':'FRESH'))}</td><td>${chip(v.available?'AVAILABLE':v.health!=='OPERABLE'?v.health:'UNAVAILABLE')}</td><td>${state.actor.role==='student'&&v.available?actionButton('Reserve · 10 min','reserve_vehicle',{vehicle_id:v.id},'small'):'—'}</td></tr>`).join('')}</tbody></table></div>`:empty('No shared vehicles here','Choose another hub or check back after a verified arrival.')}<p class="muted small-text spaced">A vehicle hold lasts 10 minutes. Destination parking is reserved separately. Stale observations cannot support a new allocation.</p>`;
}

function journeys() {
  const holds=list('holds').slice().reverse(), trips=list('trips').slice().reverse();
  const openTrips=trips.filter(t=>t.status!=='CLOSED');
  return heading('Rentals and journeys', 'Your journey, end to end', 'Present your reservation QR at the Hub. Pickup and return status update after external verification.')+
    `<div class="split"><section><div class="section-heading"><h2>Vehicle reservations</h2><button class="link" data-tab="overview">Find a vehicle →</button></div><div class="records">${holds.length?holds.map(h=>`<article class="record"><div class="record-main"><div><div class="record-title"><h3>${esc(vehicleName(h.vehicle_id))}</h3><span class="record-id">${esc(h.id)}</span></div><div class="record-meta"><span>Hold until ${date(h.expires_at)}</span></div></div>${chip(h.status)}</div>${rentalQrButton(h)}${h.status==='ACTIVE'?`<div class="record-actions">${actionButton('Cancel reservation','cancel_hold',{hold_id:h.id},'danger small')}</div>`:''}${/PENDING/.test(h.status)?'<div class="record-note">Handover is awaiting evidence. Expiry and cancellation will not silently free this vehicle.</div>':''}</article>`).join(''):empty('No vehicle reservations yet','Reserve an eligible shared vehicle from Explore hubs.')}</div><div class="section-heading"><h2>Journeys</h2></div><div class="records">${trips.length?trips.map(t=>`<article class="record"><div class="record-main"><div><div class="record-title"><h3>${esc(vehicleName(t.vehicle_id))}</h3><span class="record-id">${esc(t.id)}</span></div><div class="record-meta"><span>Started ${date(t.started_at)}</span><span>${t.ended_at?'Returned '+date(t.ended_at):'Handover responsibility remains open'}</span></div></div>${chip(t.status)}</div>${t.status==='ASSISTANCE_PENDING'?'<div class="record-note">Reception needs operator assistance. Your trip remains open; see Support for a capacity proposal.</div>':''}</article>`).join(''):empty('Your next journey starts here','A trip appears after pickup evidence has been accepted.')}</div></section><aside><div class="card"><div class="card-body"><div class="eyebrow">Plan your return</div><h2>Choose your return destination</h2><p class="muted small-text spaced">Save your preferred destination before returning. This selection does not confirm physical return or reserve a bay.</p><form class="form spaced" data-command="select_return_hub"><label>Open trip<select name="trip_id" required>${option('','Choose a trip')}${openTrips.map(t=>option(t.id,`${t.id} · ${t.vehicle_id}`)).join('')}</select></label><label>Destination hub<select name="hub_id" required>${hubOptions()}</select></label><label>Existing return parking right (optional)<select name="right_id">${option('','No existing parking right')}${list('rights').filter(r=>['CONFIRMED','HANDOVER_PENDING'].includes(r.status)).map(r=>option(r.id,`${r.id} · ${hubName(r.hub_id)} · ${r.vehicle_id}`)).join('')}</select></label><button type="submit">Save return destination</button></form></div></div><div class="card spaced"><div class="card-body"><h3>Need a place at your destination?</h3><p class="muted small-text spaced">A hold does not include a return bay. Reserve a separate shared-vehicle parking right before arrival.</p><button class="link spaced" data-tab="parking">Reserve parking →</button></div></div></aside></div>`;
}

const hubOptions = () => list('hubs').map(h=>option(h.id,h.name,selectedHub===h.id)).join('');
const myVehicles = () => list('vehicles').filter(v=>v.owner_id===state.actor.id || (v.kind==='shared' && [...list('holds'),...list('trips')].some(r=>r.owner_id===state.actor.id&&r.vehicle_id===v.id&&!['CANCELLED','EXPIRED','CONSUMED','CLOSED'].includes(r.status))));

function parking() {
  const rights=list('rights').slice().reverse(), visits=list('visits').slice().reverse();
  return heading('Parking and capacity', 'A place when you need it', 'Reserve up to 24 hours ahead. Personal parking lasts 15 minutes to 12 hours, with a 15-minute gap before the next reservation.')+
    `<div class="split"><section><div class="section-heading"><h2>Parking rights</h2></div><div class="records">${rights.length?rights.map(r=>`<article class="record"><div class="record-main"><div><div class="record-title"><h3>${esc(hubName(r.hub_id))}</h3><span class="record-id">${esc(r.id)}</span></div><div class="record-meta"><span>${esc(vehicleName(r.vehicle_id))}</span><span>Bay ${esc(r.spot_id)}</span></div><p class="muted small-text">${date(r.start)} → ${r.end?date(r.end):'Verified departure'}</p></div>${chip(r.status)}</div><div class="record-actions">${parkingQrButton(r)}</div>${r.status==='CONFIRMED'?`<div class="record-actions">${actionButton('Cancel unused right','cancel_parking',{right_id:r.id},'danger small')}</div>`:''}${r.status==='HANDOVER_PENDING'?'<div class="record-note">Arrival evidence is pending. This commitment remains protected.</div>':''}</article>`).join(''):empty('No parking rights yet','Reserve a bay, or reserve parking and charging together.')}</div><div class="section-heading"><h2>Observed visits</h2></div><div class="records">${visits.length?visits.map(v=>`<article class="record"><div class="record-main"><div><h3>${esc(vehicleName(v.vehicle_id))}</h3><div class="record-meta"><span>Bay ${esc(v.spot_id)}</span><span class="record-id">${esc(v.id)}</span></div></div>${chip(v.status)}</div><div class="record-note">Elapsed booking time never frees a physically occupied bay. Departure requires evidence and a disconnected charger.</div></article>`).join(''):empty('No recorded visits','An accepted arrival event creates an occupied visit.')}</div></section><aside><div class="card"><div class="card-body"><div class="eyebrow">Reserve your space</div><h2>Parking, with options</h2><form class="form spaced" data-command="reserve_parking"><label>Vehicle<select name="vehicle_id" required>${option('','Choose your vehicle')}${myVehicles().map(v=>option(v.id,vehicleName(v.id))).join('')}</select></label><label>Hub<select name="hub_id" required>${hubOptions()}</select></label><label>Arrival time<input name="start" type="datetime-local" required value="${inputDate(now()+120)}"></label><label>Expected departure<input name="end" type="datetime-local" required value="${inputDate(now()+3720)}"><span class="form-help">Shared vehicles occupy their return bay until verified departure.</span></label><label class="check-label"><input type="checkbox" name="charging">Include charging (personal vehicles)</label><label>Charging target SOC (%)<input name="target_soc" type="number" min="1" max="100" value="80"></label><label>Link to active vehicle hold (optional)<select name="hold_id">${option('','Independent parking right')}${list('holds').filter(h=>h.status==='ACTIVE').map(h=>option(h.id,`${h.id} · ${h.vehicle_id}`)).join('')}</select></label><button type="submit">Confirm reservation</button><p class="form-help">A charging bundle commits both resources together. It will not silently fall back to parking alone.</p></form></div></div><div class="card spaced"><div class="card-body"><h3>Register a personal vehicle</h3>${vehicleForm()}</div></div></aside></div>`;
}

function vehicleForm() {
  return `<form class="form spaced" data-command="register_vehicle"><label>Vehicle name<input name="label" maxlength="80" required placeholder="My electric bicycle"></label><div class="form-row"><label>Battery capacity (kWh)<input name="battery_kwh" type="number" min="0.1" max="100" step="0.1" value="2" required></label><label>Current SOC (%)<input name="soc" type="number" min="0" max="99" value="30" required></label></div><label>Connector<select name="connector">${option('TYPE2','Type 2')}${option('SCHUKO','Schuko')}</select></label><button class="secondary" type="submit">Register vehicle</button><p class="form-help">Declared battery data is used for estimates; it is not a physical measurement.</p></form>`;
}

function charging() {
  const sessions=list('sessions').slice().reverse();
  const eligibleRights=compatibleChargingRights();
  return heading('Charging services', 'Charge with confidence', 'Book charging directly, then receive your allocation and QR after operator confirmation.')+chargingRequestForm()+chargingRequestCards()+`<section class="spaced"><div class="card"><div class="card-body"><div class="eyebrow">Use an existing parking right</div><h2>Add charging</h2><form class="form spaced" data-command="register_charge"><label>Parking right<select name="right_id" required>${option('','Choose a compatible right')}${eligibleRights.map(r=>option(r.id,`${r.id} · ${r.vehicle_id} · ${r.spot_id}`)).join('')}</select></label><label>Target SOC (%)<input type="number" name="target_soc" min="1" max="100" value="80" required></label><button type="submit">Reserve charging</button><p class="form-help">The right must cover the session window and belong to a compatible charging bay. Independently created parking rights are preserved when charging is canceled.</p></form></div></div><div class="card spaced"><div class="card-body"><h3>How a session progresses</h3><ol class="review-list"><li>Reserve parking and charging.</li><li>Present your QR at the assigned bay; await verification.</li><li>Connect your vehicle; await connection evidence.</li><li>Charging starts after verified connection and power acknowledgement.</li><li>Stop charging if needed; await power-off acknowledgement.</li><li>Unplug and collect your vehicle; departure updates after verification.</li></ol></div></div></section>`+
    `<div><section><div class="section-heading"><h2>Charging sessions</h2><button class="link" data-tab="parking">Book parking + charging →</button></div><div class="records">${sessions.length?sessions.map(s=>{const port=find('ports',s.port_id);return `<article class="record"><div class="record-main"><div><div class="record-title"><h3>${esc(vehicleName(s.vehicle_id))}</h3><span class="record-id">${esc(s.id)}</span></div><div class="record-meta"><span>Port ${esc(s.port_id)}</span><span>Target ${esc(s.target_soc)}%</span><span>${esc(s.kw||'—')} kW</span></div><p class="muted small-text">Window ${date(s.start)} → ${date(s.end)}</p><p class="muted small-text">Scheduled ${date(s.scheduled_start)} → ${date(s.scheduled_end)}</p></div>${chip(s.status)}</div><div class="record-note">Physical port: ${esc(title(port?.plug||'UNKNOWN'))} · Power ${esc(title(port?.power||'UNKNOWN'))} · ${esc(title(port?.health||'UNKNOWN'))}</div><div class="record-actions">${s.status==='BOOKED'?actionButton('Cancel unused session','cancel_charge',{session_id:s.id},'danger small'):''}${['CHARGING','START_PENDING','STOP_PENDING'].includes(s.status)?actionButton('Stop charging','stop_charge',{session_id:s.id},'small'):''}</div>${s.status==='COMPLETED'?'<p class="muted small-text spaced">Session complete. The port remains occupied until unplugging is observed; the parking bay remains occupied until departure.</p>':''}</article>`;}).join(''):empty('No charging sessions','Create a parking + charging bundle, or add charging to a compatible existing right.')}</div><div class="section-heading"><h2>Ports and observations</h2></div><div class="table-wrap"><table><thead><tr><th>Port / bay</th><th>Connection</th><th>Power</th><th>Health</th><th>Observation</th></tr></thead><tbody>${list('ports').map(p=>`<tr><td>${esc(p.id)} / ${esc(p.spot_id)}</td><td>${chip(p.plug)}</td><td>${chip(p.power)}</td><td>${chip(p.health)}</td><td>${chip(p.freshness||(now()-p.observed_at>90?'STALE':'FRESH'))}</td></tr>`).join('')}</tbody></table></div></section></div>`;
}

function receptionOffer(incident) {
  const right = find('rights',incident.offered_right_id);
  if (!right) return '';
  return `<div class="record-note"><strong>Proposed reception · ${esc(hubName(right.hub_id))}</strong>
    <p>Bay ${esc(right.spot_id)} for ${esc(vehicleName(right.vehicle_id))}. Respond by ${date(incident.offer_expires_at)}.</p></div>`;
}

function support() {
  const records=[...list('holds'),...list('trips'),...list('rights'),...list('visits'),...list('sessions')];
  return heading('Journey assistance', 'Support that stays with you', 'Keep a traceable record of an issue or reception problem. Operator proposals require your response and never close a trip by themselves.')+
    `<div class="split"><section><div class="section-heading"><h2>Support records</h2></div><div class="records">${list('incidents').length?list('incidents').slice().reverse().map(i=>`<article class="record"><div class="record-main"><div><h3>${esc(i.message||'Reception assistance')}</h3><div class="record-meta"><span class="record-id">${esc(i.id)}</span><span>Related record ${esc(i.record_id)}</span></div></div>${chip(i.status)}</div>${i.response?`<div class="record-note">${
  typeof i.response === 'string'
    ? esc(i.response)
    : detailValue(i.response)
}</div>`:''}${i.status==='OFFERED' ? receptionOffer(i) : ''}${state.actor.role==='student'&&i.status==='OFFERED'?`<div class="record-actions">${actionButton('Accept proposed reception','accept_capacity',{incident_id:i.id,accept:true},'small')}${actionButton('Decline proposal','accept_capacity',{incident_id:i.id,accept:false},'danger small')}</div>`:''}</article>`).join(''):empty('No support records','You can report an issue against one of your own service records.')}</div></section><aside><div class="card"><div class="card-body"><h2>Request support</h2><form class="form spaced" data-command="support"><label>Related service<select name="record_id" required>${option('','Select a service record')}${records.map(r=>option(r.id,`${r.id} · ${r.vehicle_id||r.status}`)).join('')}</select></label><label>What happened?<textarea name="message" required minlength="5" maxlength="1000" placeholder="Describe the problem and where you are."></textarea></label><button type="submit">Send support request</button><p class="form-help">An operator can use this report to open a maintenance ticket for the affected resource.</p></form></div></div></aside></div>`;
}

function operations() {
  const commands=list('commands');
  const capacityCases=list('incidents').filter(i => {
    if (!['OPEN','WAITING_FOR_D','DECLINED'].includes(i.status)) return false;
    const trip=find('trips',i.record_id), right=find('rights',i.record_id);
    return (trip && trip.status!=='CLOSED') || right?.status==='CONFIRMED';
  });
  const fleetVehicles=list('vehicles').filter(v => v.kind==='shared' && !v.transfer_order_id &&
    v.health==='OPERABLE' && v.soc < 100 && list('ports').some(p=>p.spot_id===v.spot_id && p.connector===v.connector));
  return heading('Operator workspace', 'Keep the network moving', 'Review reception proposals and charging schedules. Confirming a plan does not assert that a physical movement has happened.')+chargingRequestCards(true)+
    `<div class="grid two"><div class="card"><div class="card-body"><div class="eyebrow">B05 · Recovery capacity</div><h2>Propose a reception option</h2><form class="form spaced" data-command="capacity_plan"><label>Support case<select name="incident_id" required>${option('','Choose an unresolved case')}${capacityCases.map(i=>option(i.id,`${i.id} · ${i.message||i.record_id}`)).join('')}</select></label><label>Recovery hub<select name="hub_id" required>${hubOptions()}</select></label><label>Reason for reserve capacity<input name="reason" required minlength="5" maxlength="500" placeholder="Protect reception for an interrupted journey"></label><button type="submit">Propose reception</button><p class="form-help">Capacity is rechecked; existing commitments are protected. The owner must accept the proposal before requesting handover.</p></form></div></div><div class="card"><div class="card-body"><div class="eyebrow">C03 · Charging allocation</div><h2>Preview the charging schedule</h2><p class="muted spaced">Build a plan using current session demand, port compatibility, fresh observations and hub power limits. Confirmation checks the current revision again.</p><div class="record-actions">${actionButton('Create schedule preview','schedule_preview',{},'')}</div><div class="records spaced">${list('plans').filter(p=>p.kind!=='capacity').slice().reverse().map(p=>`<article class="record"><div class="row-spread"><span class="record-id">${esc(p.id)}</span>${chip(p.status)}</div><div class="record-actions"><button class="secondary small" data-detail="plans" data-id="${esc(p.id)}">Review allocation</button>${['DRAFT','PROPOSED','PREVIEW'].includes(p.status)?actionButton('Confirm schedule','schedule_confirm',{plan_id:p.id},'small'):''}</div></article>`).join('')||'<p class="muted small-text">No schedule previews yet.</p>'}</div></div></div></div>`+
    `<section class="card spaced"><div class="card-body"><h2>Schedule fleet charging</h2>
      ${fleetVehicles.length?`<form class="form spaced" data-command="fleet_charge"><div class="form-row">
      <label>Fleet vehicle at a charging bay<select name="vehicle_id" required>${fleetVehicles.map(v=>option(v.id,`${v.id} · ${v.spot_id} · ${v.soc}%`)).join('')}</select></label>
      <label>Target charge (%)<input type="number" name="target_soc" min="1" max="100" value="90" required></label></div>
      <button type="submit">Book fleet charging</button></form>`:'<p class="muted spaced">A shared vehicle must be parked at a compatible charging bay before scheduling.</p>'}
      <button class="link spaced" data-tab="charging">Manage charging sessions →</button></div></section>`+
    `<div class="section-heading"><h2>Device command outbox</h2><span class="muted small-text">Persisted intent · acknowledgement required</span></div><div class="records">${commands.length?commands.slice().reverse().map(c=>`<article class="record"><div class="record-main"><div><div class="record-title"><h3>${esc(title(c.kind))}</h3><span class="record-id">${esc(c.id)}</span></div><div class="record-meta"><span>Record ${esc(c.record_id)}</span>${c.vehicle_id?`<span>Vehicle ${esc(c.vehicle_id)}</span>`:''}<span>Created ${date(c.created_at)}</span></div></div>${chip(c.status)}</div>${state.simulator&&!['ACK','ACKNOWLEDGED','CONFIRMED','APPLIED','REJECTED','COMPLETED'].includes(c.status)?`<div class="record-actions">${actionButton('Simulate ACK','simulate',{command_id:c.id,outcome:'ACK'},'small')}${actionButton('Simulate rejection','simulate',{command_id:c.id,outcome:'REJECT'},'danger small')}${actionButton('Simulate unknown outcome','simulate',{command_id:c.id,outcome:'UNKNOWN'},'secondary small')}</div><p class="muted small-text spaced">Synthetic test evidence only. No device is contacted.</p>`:''}</article>`).join(''):empty('No pending device requests','Device handover and charging commands are recorded here.')}</div>`+
    (state.simulator?`<section class="sim-area spaced"><div class="row-spread"><div><div class="eyebrow">Controlled test environment</div><h2>Synthetic observation controls</h2></div>${actionButton('Refresh simulated observations','sim_refresh',{},'secondary small')}</div><p class="muted small-text spaced">Refresh renews only simulated observations. Fault controls exercise eligibility and failure handling. These controls are disabled unless the server starts with --simulator.</p><form class="form spaced" data-command="sim_observe"><div class="form-row"><label>Resource<select name="resource_ref">${['ports','vehicles','spots'].flatMap(key=>list(key).map(r=>option(`${key}:${r.id}`,`${title(key)} · ${r.id}`))).join('')}</select></label><label>Technical condition<select name="health">${option('OUT_OF_SERVICE','Out of service')}${option('OPERABLE','Operable')}</select></label></div><button type="submit" class="secondary">Submit synthetic observation</button></form></section>`:'')+
    `<div class="section-heading"><h2>Unresolved assistance</h2><button class="link" data-tab="support">View support records →</button></div><p class="muted">${list('incidents').filter(i=>!['RESOLVED','CLOSED'].includes(i.status)).length} support records need review. <button class="link" data-tab="network">Open fleet operations →</button></p>`;
}
// ==========================================
// STRUCTURED DETAIL & AUDIT RENDERER
// ==========================================

const detailHidden = new Set([
  'token',
  'qr_token',
  'password',
  'secret',
  'access_token',
  'refresh_token',
  'input_fingerprint'
]);

const detailFields = record =>
  Object.entries(record || {})
    .filter(([key]) => !detailHidden.has(key));

function detailValue(value, key = '') {
  if (value == null || value === '') {
    return '—';
  }

  if (typeof value === 'boolean') {
    return value ? 'Yes' : 'No';
  }

  if (Array.isArray(value)) {
    return value.length
      ? `<ol class="detail-items">
          ${value.map(item =>
            `<li>${detailValue(item)}</li>`
          ).join('')}
        </ol>`
      : '<span class="muted">None</span>';
  }

  if (typeof value === 'object') {
    return detailRecord(value);
  }

  if (typeof value === 'number') {
    if (
      /(_at$|^at$|^start$|^end$|_start$|_end$)/.test(key)
      && value > 1e9
    ) {
      return esc(
        new Date(value * 1000).toLocaleString()
      );
    }

    if (['soc', 'target_soc', 'declared_soc'].includes(key)) {
      return `${esc(value)}%`;
    }
  }

  if (
    [
      'status',
      'health',
      'state',
      'freshness',
      'plug',
      'power'
    ].includes(key)
  ) {
    return chip(value);
  }

  return esc(value);
}

function detailRecord(record) {
  const rows = detailFields(record);

  return rows.length
    ? `<dl class="detail-grid">
        ${rows.map(([key, value]) => `
          <div class="detail-field">
            <dt>${esc(title(key))}</dt>
            <dd>${detailValue(value, key)}</dd>
          </div>
        `).join('')}
      </dl>`
    : '<p class="muted">No additional data.</p>';
}

function auditChanges(audit) {
  const records = new Map();

  for (const side of ['before', 'after']) {
    const items = Array.isArray(audit[side])
      ? audit[side]
      : [];

    for (const item of items) {
      const key = `${item.kind}:${item.id}`;

      if (!records.has(key)) {
        records.set(key, {
          kind: item.kind,
          id: item.id,
          before: null,
          after: null
        });
      }

      records.get(key)[side] = item.value;
    }
  }

  return [...records.values()];
}

function auditDetail(audit) {
  const changes = auditChanges(audit);

  return changes.length
    ? changes.map(change => {

        const before = Object.fromEntries(
          detailFields(change.before)
        );

        const after = Object.fromEntries(
          detailFields(change.after)
        );

        const keys = [
          ...new Set([
            ...Object.keys(before),
            ...Object.keys(after)
          ])
        ];

        const rows = keys
          .map(key => ({
            key,
            old: detailValue(before[key], key),
            next: detailValue(after[key], key)
          }))
          .filter(row => row.old !== row.next);

        const record =
          change.after || change.before || {};

        const operation =
          change.before == null
            ? 'Created'
            : change.after == null
              ? 'Removed'
              : 'Updated';

        return `
          <section class="detail-change">
            <div class="row-spread">
              <h3>${esc(title(change.kind))}</h3>
              <span class="chip neutral">
                ${operation}
              </span>
            </div>

            <p class="record-id">
              ${esc(change.id)}
            </p>

            ${
              record.vehicle_id
                ? `<p class="small-text">
                     Vehicle: ${esc(record.vehicle_id)}
                   </p>`
                : ''
            }

            ${
              rows.length
                ? `<div class="table-wrap spaced">
                    <table class="detail-diff">
                      <thead>
                        <tr>
                          <th>Field</th>
                          <th>Before</th>
                          <th>After</th>
                        </tr>
                      </thead>

                      <tbody>
                        ${rows.map(row => `
                          <tr>
                            <th scope="row">
                              ${esc(title(row.key))}
                            </th>
                            <td>${row.old}</td>
                            <td>${row.next}</td>
                          </tr>
                        `).join('')}
                      </tbody>
                    </table>
                  </div>`
                : `<p class="muted">
                     No visible field changes.
                   </p>`
            }
          </section>
        `;
      }).join('')
    : '<p class="muted">No recorded field changes.</p>';
}
function activityHistory() {
  const records = list('audit').slice().reverse();

  return heading(
    'Evidence and history',
    'Activity History',
    'Review recorded actions and changes across the system.'
  ) + (
    records.length
      ? `
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Detail</th>
              </tr>
            </thead>

            <tbody>
              ${records.map(a => `
                <tr>
                  <td>${date(a.at)}</td>

                  <td>
                    ${esc(a.actor_id || a.actor || 'system')}
                  </td>

                  <td>
                    ${esc(title(a.action || a.kind))}
                  </td>

                  <td class="history-detail">
                    ${
                      auditChanges(a).length
                        ? `
                          <span class="small-text muted">
                            ${auditChanges(a).length} record(s)
                          </span>

                          <br>

                          <button
                            type="button"
                            class="secondary small"
                            data-detail="audit"
                            data-id="${esc(a.id)}"
                          >
                            View changes
                          </button>
                        `
                        : '<span class="muted">—</span>'
                    }
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>  
      `
      : empty(
          'No activity recorded yet',
          'Complete a reservation or request to begin your history.'
        )
  );
}

app.addEventListener('click', async event => {
  const button=event.target.closest('button');
  if (!button) return;
  if (button.dataset.tab) {
    tab=button.dataset.tab;
    window.history.replaceState(null, '', '#' + tab);
    render();
    window.scrollTo(0,0);
  }
  else if (button.dataset.hub) {selectedHub=button.dataset.hub;render();document.querySelector('#hub-filter')?.scrollIntoView({behavior:'smooth',block:'center'});}
  else if (button.dataset.action) await command(button.dataset.action, JSON.parse(button.dataset.payload));
  else if (button.dataset.serviceQr) await showServiceQr(button.dataset.serviceQr,button.dataset.id);
  else if (button.dataset.parkingQr) await showParkingQr(button.dataset.parkingQr);
  else if (button.id==='refresh') await refresh();
  else if (button.id==='logout') {refreshVersion++;try {await request('/api/logout',{});refreshVersion++;state=null;notice.hidden=true;window.history.replaceState(null,'',location.pathname);renderLogin();}catch(error){showNotice(error.message,true);}}
  else if (button.dataset.detail) {
    const record = find(
      button.dataset.detail,
      button.dataset.id
    );

    const content = document.querySelector(
      '#detail-content'
    );

    if (!record) {
      return showNotice('Record not found.', true);
    }

    content.innerHTML =
      button.dataset.detail === 'audit'
        ? `
          <h2>
            Activity detail —
            ${esc(title(record.action || record.kind))}
          </h2>

          <p class="muted spaced">
            ${esc(
              record.actor_id ||
              record.actor ||
              'system'
            )}
            · ${esc(date(record.at))}
          </p>

          ${auditDetail(record)}
        `
        : `
          <h2>Review allocation</h2>

          <p class="muted spaced">
            ${esc(record.id)}
          </p>

          ${detailRecord(record)}
        `;

    document
      .querySelector('#detail-dialog')
      .showModal();
  }
  else if (button.id === 'recover-pending') {
      await command(null, null, true);
  }
});

app.addEventListener('change', event => {
  if(event.target.matches('form[data-command="sim_iot_event"] select[name="record_id"]')) {
    const form=event.target.form;
    const record=[...list('sessions'),...list('visits'),...list('trips')].find(r=>r.id===event.target.value);
    if(record) {
      const right=find('rights',record.right_id||record.return_right_id);
      const port=find('ports',record.port_id);
      form.elements.vehicle_id.value=record.vehicle_id;
      if(right?.hub_id||port?.hub_id) form.elements.hub_id.value=right?.hub_id||port?.hub_id;
      form.elements.spot_id.value=record.spot_id||right?.spot_id||port?.spot_id||'';
      form.elements.port_id.value=record.port_id||'';
    }
  }
  if (event.target.matches('form[data-command="submit_charge_request"] select[name="vehicle_id"]')) { const vehicle=find('vehicles',event.target.value); if(vehicle) event.target.form.elements.declared_soc.value=vehicle.soc; }
  if (event.target.id==='hub-filter') {selectedHub=event.target.value;render();}
});

app.addEventListener('input',event=>{if(event.target.form) event.target.form.dataset.dirty='true';});
app.addEventListener('change',event=>{if(event.target.form) event.target.form.dataset.dirty='true';});

app.addEventListener('submit', async event => {
  event.preventDefault();
  const form=event.target;
  if (form.id==='login-form') {
    const submit=form.querySelector('button'); submit.disabled=true;
    try {
      const {actor}=await request('/api/login',Object.fromEntries(new FormData(form)));
      tab=actor.role==='student'?'overview':'network';
      window.history.replaceState(null,'','#'+tab);
      await refresh();
    }
    catch(error) {document.querySelector('#login-error').textContent=error.message;}
    finally {submit.disabled=false;}
    return;
  }
  if (!form.dataset.command) return;
  const values=new FormData(form);
  const payload=Object.fromEntries(values);
  if(form.dataset.command==='sim_iot_event') payload.event_id=crypto.randomUUID();
  if(form.dataset.command==='sim_iot_event') for(const key of ['spot_id','port_id']) if(!payload[key]) delete payload[key];
  if (form.closest('#fleet-workspace') && !prepareFleetCommand(form, values, payload)) return;
  for (const key of ['start','end','arrival_time']) if (key in payload) payload[key]=new Date(payload[key]).getTime()/1000;
  for (const key of ['target_soc','declared_soc','battery_kwh','soc']) if (key in payload) payload[key]=Number(payload[key]);
  if (form.dataset.command==='reserve_parking') payload.charging=form.elements.charging.checked;
  for (const key of ['right_id','hold_id']) if (payload[key]==='') delete payload[key];
  if (payload.resource_ref) {const [resource_type,resource_id]=payload.resource_ref.split(':');delete payload.resource_ref;Object.assign(payload,{resource_type,resource_id});}
  await command(form.dataset.command,payload);
});

notice.addEventListener('click', event => {
    const button = event.target.closest(
        'button[data-notice]'
    );

    if (!button) return;

    if (button.dataset.notice === 'retry') {
        command(null, null, true);
    } else {
        hideNotice();
    }
});

document.querySelector('#close-dialog').addEventListener('click',()=>document.querySelector('#detail-dialog').close());
let autoRefreshing = false;

async function autoRefresh() {
    if (
        !state ||
        busy ||
        document.hidden ||
        autoRefreshing
    ) {
        return;
    }

    autoRefreshing = true;

    try {
        await refresh(true, true);
    } finally {
        autoRefreshing = false;
    }
}

refresh();

setInterval(autoRefresh, 4000);

document.addEventListener(
    'visibilitychange',
    () => {
        if (!document.hidden) {
            autoRefresh();
        }
    }
);

window.addEventListener('focus', autoRefresh);
