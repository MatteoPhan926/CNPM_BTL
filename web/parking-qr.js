'use strict';

const parkingQrDialog = document.querySelector('#parking-qr-dialog');
let parkingQrRight = null;
let parkingQrRequest = 0;
let parkingQrTimer;

function clearParkingQr() {
  parkingQrRequest++;
  parkingQrRight = null;
  clearTimeout(parkingQrTimer);
  document.querySelector('#parking-qr-content').replaceChildren();
  document.querySelector('#parking-qr-feedback').hidden = true;
}

async function loadParkingQr() {
  if (!parkingQrDialog.open || !parkingQrRight || !state) return;
  const requestId = ++parkingQrRequest, rightId = parkingQrRight, actorId = state.actor.id;
  clearTimeout(parkingQrTimer);
  try {
    const qr = await request('/api/parking-qr?right_id=' + encodeURIComponent(rightId));
    if (requestId !== parkingQrRequest || !parkingQrDialog.open || state?.actor.id !== actorId) return;
    const right = find('rights', rightId);
    const personal = find('vehicles', right?.vehicle_id)?.kind === 'personal';
    document.querySelector('#parking-qr-content').innerHTML = `
      <div class="eyebrow">Parking confirmation</div><h2 id="parking-qr-title">Your parking QR</h2>
      <p class="spaced" id="parking-qr-status">${chip(qr.status)} ${esc(qr.message)}</p>
      <img class="parking-qr-image" alt="Parking reservation QR code" src="data:image/svg+xml;charset=utf-8,${encodeURIComponent(qr.svg)}">
      <dl class="parking-qr-details">
        <dt>Reservation ID</dt><dd>${esc(rightId)}</dd>
        <dt>Vehicle</dt><dd>${esc(vehicleName(right?.vehicle_id))}</dd>
        <dt>Hub</dt><dd>${esc(hubName(right?.hub_id))}</dd>
        <dt>Parking bay</dt><dd>${esc(right?.spot_id)}</dd>
        <dt>Arrival time</dt><dd>${esc(date(right?.start))}</dd>
        <dt>Arrival code valid until</dt><dd>${esc(date(qr.expires_at))}</dd>
      </dl>
      <label>Confirmation code<input id="parking-qr-token" readonly value="${esc(qr.token)}"></label>
      <p class="muted small-text spaced">A valid QR requests admission only. Parking is confirmed after reception evidence arrives. Early arrival is subject to availability checks.</p>
      ${personal && qr.usable ? actionButton('Request arrival', 'arrive', {right_id:rightId, qr_token:qr.token}, 'spaced') : ''}
      ${!personal ? '<p class="muted small-text spaced">Shared vehicles use Request return in My journeys.</p>' : ''}`;
    // Recheck while the modal is open, including cancellation/ACK in another context.
    parkingQrTimer = setTimeout(loadParkingQr, 5000);
  } catch (error) {
    if (requestId !== parkingQrRequest || !parkingQrDialog.open) return;
    document.querySelector('#parking-qr-content').innerHTML = `<h2 id="parking-qr-title">Parking QR unavailable</h2><p class="spaced">${esc(error.message)}</p>`;
  }
}

async function showParkingQr(rightId) {
  parkingQrRight = rightId;
  document.querySelector('#parking-qr-content').innerHTML = '<h2 id="parking-qr-title">Loading parking QR…</h2>';
  if (!parkingQrDialog.open) parkingQrDialog.showModal();
  await loadParkingQr();
}

parkingQrDialog.addEventListener('close', clearParkingQr);
document.querySelector('#close-parking-qr').addEventListener('click', () => parkingQrDialog.close());
parkingQrDialog.addEventListener('click', async event => {
  const button = event.target.closest('button[data-action="arrive"]');
  if (!button) return;
  const rightId = parkingQrRight, actorId = state?.actor.id;
  button.disabled = true;
  const result = await command('arrive', JSON.parse(button.dataset.payload));
  if (!parkingQrDialog.open || parkingQrRight !== rightId || state?.actor.id !== actorId) return;
  await loadParkingQr();
  const feedback = document.querySelector('#parking-qr-feedback');
  feedback.hidden = !result?.error;
  feedback.textContent = result?.error ? result.error + (result.retry ? ' Close this dialog and choose Retry same request.' : '') : '';
});

function parkingQrButton(right) {
  if (!right.qr || right.owner_id !== state.actor.id) return '';
  return `<button type="button" class="secondary small" data-parking-qr="${esc(right.id)}">Show parking QR</button>`;
}

function parkingCodeForm() {
  if (state.actor.role !== 'student') return '';
  return `<section class="card spaced"><div class="card-body"><h3>Check in with a parking code</h3>
    <p class="muted small-text spaced">Paste the text read from your QR. Reception still requires confirmation.</p>
    <form class="form spaced" data-command="arrive"><label>Parking confirmation code<input name="qr_token" required maxlength="128" autocomplete="off" spellcheck="false"></label>
    <button type="submit">Request arrival with code</button></form></div></section>`;
}
