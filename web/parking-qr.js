'use strict';

const parkingQrDialog = document.querySelector('#parking-qr-dialog');

let parkingQrRight = null;
let parkingQrRequest = 0;
let parkingQrTimer;

function renderQrContents(selector, markup) {
    const content = document.querySelector(selector);

    if (content._qrMarkup === markup) {
        return;
    }

    content._qrMarkup = markup;
    content.innerHTML = markup;
}

function clearParkingQr() {
    parkingQrRequest++;
    parkingQrRight = null;

    clearTimeout(parkingQrTimer);

    renderQrContents('#parking-qr-content', '');

    document.querySelector('#parking-qr-feedback').hidden = true;
}

const parkingQrMessages = {
    'Valid for an arrival request. Reception conditions will be checked again.':
        'Mã hợp lệ để yêu cầu vào bãi. Điều kiện tiếp nhận sẽ được kiểm tra lại.',

    'Arrival requested; awaiting reception evidence. Do not check in again.':
        'Đã yêu cầu vào bãi, đang chờ bằng chứng tiếp nhận. Không thực hiện check-in lại.',

    'Already used. This code cannot start a second parking visit.':
        'Mã đã được sử dụng và không thể tạo thêm lượt đỗ xe khác.',

    'Reservation cancelled. This code is no longer valid.':
        'Lượt đặt chỗ đã bị hủy. Mã QR không còn hiệu lực.',

    'Reservation expired. This code is no longer valid.':
        'Lượt đặt chỗ đã hết hạn. Mã QR không còn hiệu lực.',

    'Alternative reception has not yet been accepted.':
        'Phương án tiếp nhận thay thế chưa được chấp nhận.',

    'This code is not valid for check-in.':
        'Mã QR không hợp lệ để xác nhận vào bãi.',

    'Arrival grace period has elapsed. This code is no longer valid.':
        'Đã quá thời hạn cho phép vào bãi. Mã QR không còn hiệu lực.'
};

const parkingQrMessage = message =>
    parkingQrMessages[message] || message;

async function loadParkingQr() {
    if (!parkingQrDialog.open || !parkingQrRight || !state) {
        return;
    }

    const requestId = ++parkingQrRequest,
          rightId = parkingQrRight,
          actorId = state.actor.id;

    clearTimeout(parkingQrTimer);

    try {
        const qr = await request(
            '/api/parking-qr?right_id=' + encodeURIComponent(rightId)
        );

        if (
            requestId !== parkingQrRequest ||
            !parkingQrDialog.open ||
            state?.actor.id !== actorId
        ) {
            return;
        }

        const right = find('rights', rightId);

        renderQrContents(
            '#parking-qr-content',
            `
            <div class="eyebrow">
                Xác nhận đỗ xe
            </div>

            <h2 id="parking-qr-title">
                Mã QR đỗ xe của bạn
            </h2>

            <p class="spaced" id="parking-qr-status">

                ${chip(qr.status)}

                ${esc(parkingQrMessage(qr.message))}

            </p>

            <img
                class="parking-qr-image"
                alt="Mã QR xác nhận đặt chỗ đỗ xe"
                src="data:image/svg+xml;charset=utf-8,${encodeURIComponent(qr.svg)}"
            >

            <dl class="parking-qr-details">

                <dt>Mã đặt chỗ</dt>
                <dd>${esc(rightId)}</dd>

                <dt>Phương tiện</dt>
                <dd>${esc(vehicleName(right?.vehicle_id))}</dd>

                <dt>Trạm</dt>
                <dd>${esc(hubName(right?.hub_id))}</dd>

                <dt>Ô đỗ xe</dt>
                <dd>${esc(right?.spot_id)}</dd>

                <dt>Thời gian đến</dt>
                <dd>${esc(date(right?.start))}</dd>

                <dt>Mã vào bãi có hiệu lực đến</dt>
                <dd>${esc(date(qr.expires_at))}</dd>

            </dl>

            <label>
                Mã xác nhận

                <input
                    id="parking-qr-token"
                    readonly
                    value="${esc(qr.token)}"
                >
            </label>

            <p class="muted small-text spaced">
                Xuất trình mã QR tại trạm hoặc ô đỗ
                được chỉ định. Trạng thái đặt chỗ sẽ
                tự động cập nhật sau khi được xác minh.
            </p>
        `
        );

        parkingQrTimer = setTimeout(loadParkingQr, 5000);

    } catch (error) {
        if (
            requestId !== parkingQrRequest ||
            !parkingQrDialog.open
        ) {
            return;
        }

        renderQrContents(
            '#parking-qr-content',
            `<h2 id="parking-qr-title">
            Mã QR đỗ xe không khả dụng
        </h2>
        <p class="spaced">
            ${esc(apiErrorText(error))}
        </p>`
        );
    }
}

async function showParkingQr(rightId) {
    parkingQrRight = rightId;

    renderQrContents(
        '#parking-qr-content',
        '<h2 id="parking-qr-title">Đang tải mã QR đỗ xe…</h2>'
    );

    if (!parkingQrDialog.open) {
        parkingQrDialog.showModal();
    }

    await loadParkingQr();
}

parkingQrDialog.addEventListener(
    'close',
    clearParkingQr
);

document
    .querySelector('#close-parking-qr')
    .addEventListener('click', () => parkingQrDialog.close());

function parkingQrButton(right) {
    if (!right.qr || right.owner_id !== state.actor.id) {
        return '';
    }

    return `
        <button
            type="button"
            class="secondary small"
            data-parking-qr="${esc(right.id)}"
        >
            Xem mã QR đỗ xe
        </button>`;
}