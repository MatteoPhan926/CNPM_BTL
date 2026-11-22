'use strict';

const parkingQrDialog = document.querySelector('#parking-qr-dialog');
let parkingQrRight = null;
let parkingQrRequest = 0;
let parkingQrTimer;

function renderQrContents(selector, markup) {
  const content=document.querySelector(selector);
  if(content._qrMarkup===markup) return;
  content._qrMarkup=markup;
  content.innerHTML=markup;
}

function clearParkingQr() {
  parkingQrRequest++;
  parkingQrRight = null;
  clearTimeout(parkingQrTimer);
  renderQrContents('#parking-qr-content','');
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
    renderQrContents('#parking-qr-content', `
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
      <p class="muted small-text spaced">Present this QR code at the assigned Hub or parking bay. Your reservation status will update automatically after verification.</p>`);
    // Recheck while the modal is open, including cancellation/ACK in another context.
    parkingQrTimer = setTimeout(loadParkingQr, 5000);
  } catch (error) {
    if (requestId !== parkingQrRequest || !parkingQrDialog.open) return;
    renderQrContents('#parking-qr-content', `<h2 id="parking-qr-title">Parking QR unavailable</h2><p class="spaced">${esc(error.message)}</p>`);
  }
}

async function showParkingQr(rightId) {
  parkingQrRight = rightId;
  renderQrContents('#parking-qr-content','<h2 id="parking-qr-title">Loading parking QR…</h2>');
  if (!parkingQrDialog.open) parkingQrDialog.showModal();
  await loadParkingQr();
}
parkingQrDialog.addEventListener('close', clearParkingQr);
document.querySelector('#close-parking-qr').addEventListener('click', () => parkingQrDialog.close());
function parkingQrButton(right) {
  if (!right.qr || right.owner_id !== state.actor.id) return '';
  return `<button type="button" class="secondary small" data-parking-qr="${esc(right.id)}">Show parking QR</button>`;
}
