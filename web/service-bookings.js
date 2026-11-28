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

    return `
        <section class="card">
            <div class="card-body">

                <div class="eyebrow">Chỉ sạc điện</div>

                <h2>Đặt chỗ sạc điện</h2>

                <p class="muted small-text spaced">
                    Không cần đặt chỗ đỗ xe trước.
                    Hệ thống đề xuất ô đỗ và thời gian sạc phù hợp
                    để nhân viên điều hành xem xét.
                </p>

                <form
                    class="form spaced"
                    data-command="submit_charge_request"
                >

                    <label>
                        Phương tiện

                        <select name="vehicle_id" required>

                            ${option(
                                '',
                                'Chọn phương tiện cá nhân'
                            )}

                            ${myVehicles()
                                .filter(v => v.kind === 'personal')
                                .map(v =>
                                    option(v.id, vehicleName(v.id))
                                ).join('')}

                        </select>
                    </label>

                    <label>
                        Trạm di chuyển

                        <select name="hub_id" required>
                            ${hubOptions()}
                        </select>
                    </label>

                    <label>
                        Mức pin hiện tại (SOC %)

                        <input
                            name="declared_soc"
                            type="number"
                            min="0"
                            max="99"
                            step="1"
                            value="30"
                            required
                        >
                    </label>

                    <label>
                        Mức pin mong muốn (SOC %)

                        <input
                            name="target_soc"
                            type="number"
                            min="1"
                            max="100"
                            step="1"
                            value="80"
                            required
                        >
                    </label>

                    <label>
                        Thời gian đến

                        <input
                            name="arrival_time"
                            type="datetime-local"
                            required
                            value="${inputDate(now() + 120)}"
                        >
                    </label>

                    <button type="submit">
                        Đăng ký sạc điện
                    </button>

                    <p class="form-help">
                        Mức pin do người dùng khai báo,
                        không phải kết quả đo từ thiết bị.
                        Mã QR xác nhận sẽ được cung cấp sau khi
                        nhân viên điều hành phê duyệt.
                        Việc vào bãi và sạc điện vẫn cần
                        bằng chứng xác nhận từ thiết bị.
                    </p>

                </form>

            </div>
        </section>`;
}



function chargingRequestCards(operator = false) {
    const requests = list('charge_requests')
        .slice()
        .reverse();

    return `
        <section class="spaced">

            <div class="section-heading">
                <h2>
                    ${operator
                        ? 'Yêu cầu sạc điện · Xét duyệt'
                        : 'Danh sách yêu cầu chỉ sạc điện'}
                </h2>
            </div>

            <div class="records">

                ${requests.length ? requests.map(r => {

                    const proposal = r.session_id
                        ? r
                        : (r.proposal || r);

                    const vehicle = find(
                        'vehicles',
                        r.vehicle_id
                    );

                    return `
                        <article class="record">

                            <div class="record-main">

                                <div>

                                    <div class="record-title">

                                        <h3>
                                            ${esc(vehicleName(r.vehicle_id))}
                                        </h3>

                                        <span class="record-id">
                                            ${esc(r.id)}
                                        </span>

                                    </div>

                                    <div class="record-meta">

                                        <span>
                                            ${esc(hubName(r.hub_id))}
                                        </span>

                                        <span>
                                            Mức pin hiện tại
                                            ${esc(r.declared_soc)}%
                                            →
                                            mục tiêu
                                            ${esc(r.target_soc)}%
                                        </span>

                                        ${operator ? `
                                            <span>
                                                Người đăng ký:
                                                ${esc(r.owner_id)}
                                            </span>
                                        ` : ''}

                                    </div>

                                </div>

                                ${chip(r.status)}

                            </div>

                            <p class="muted small-text spaced">
                                Loại dịch vụ: Chỉ sạc điện
                                · Thời gian đến
                                ${date(r.arrival_time)}
                            </p>

                            ${operator ? `
                                <p class="muted small-text">

                                    Dung lượng pin
                                    ${esc(
                                        r.battery_kwh ??
                                        vehicle?.battery_kwh
                                    )} kWh

                                    · Đầu nối
                                    ${esc(
                                        r.connector ||
                                        vehicle?.connector
                                    )}

                                </p>
                            ` : ''}

                            ${proposal.port_id ? `

                                <div class="record-note">

                                    <strong>
                                        ${r.status === 'PENDING'
                                            ? 'Đề xuất tự động'
                                            : 'Thông tin cấp phát'}
                                    </strong>

                                    <p>
                                        Ô đỗ ${esc(proposal.spot_id)}
                                        · Cổng sạc
                                        ${esc(proposal.port_id)}
                                    </p>

                                    <p>
                                        Năng lượng cần cấp:
                                        ${esc(
                                            Number(
                                                proposal.energy_kwh
                                            ).toFixed(2)
                                        )} kWh

                                        · Công suất cấp phát:
                                        ${esc(proposal.kw)} kW
                                    </p>

                                    <p>
                                        Thời gian bắt đầu dự kiến:
                                        ${date(proposal.scheduled_start)}
                                    </p>

                                    <p>
                                        Thời gian kết thúc dự kiến:
                                        ${date(proposal.scheduled_end)}

                                        · Thời lượng sạc ước tính:
                                        ${esc(
                                            Math.ceil(
                                                proposal.duration / 60
                                            )
                                        )} phút
                                    </p>

                                    <p>
                                        Thời gian nhận xe dự kiến:
                                        ${date(
                                            proposal.expected_collection_at
                                        )}
                                    </p>

                                    <p>
                                        Kết quả ước tính dựa trên
                                        mức pin đã khai báo và
                                        hiệu suất sạc 90%.
                                        Mức pin và thời điểm hoàn thành
                                        thực tế cần được thiết bị xác nhận.
                                    </p>

                                </div>

                            ` : ''}

                            ${proposal.available === false ? `

                                <p class="record-note">
                                    Không có phương án phù hợp:
                                    ${esc(apiMessageVi(proposal.reason, proposal.code))}
                                </p>

                            ` : ''}

                            ${r.rejection_reason ? `

                                <p class="record-note">
                                    Lý do từ chối:
                                    ${esc(r.rejection_reason)}
                                </p>

                            ` : ''}

                            ${r.status === 'COMPLETED' ? `

                                <p class="record-note">
                                    Quá trình sạc đã dừng.
                                    Vui lòng ngắt kết nối sạc
                                    và đưa phương tiện ra khỏi ô đỗ.
                                    Ô đỗ vẫn được ghi nhận là đang
                                    sử dụng cho đến khi việc rời bãi
                                    được xác nhận.
                                </p>

                            ` : ''}

                            ${r.status === 'PENDING' ? `

                                <p class="muted small-text spaced">
                                    Đang chờ nhân viên điều hành xác nhận.
                                    Tài nguyên đề xuất sẽ được kiểm tra
                                    lại khi phê duyệt.
                                </p>

                            ` : ''}

                            <div class="record-actions">

                                ${!operator &&
                                    r.status === 'BOOKED' ? `

                                    <button
                                        class="secondary small"
                                        data-service-qr="charging"
                                        data-id="${esc(r.id)}"
                                    >
                                        Xem mã QR sạc điện
                                    </button>

                                ` : ''}

                                ${!operator &&
                                    ['PENDING', 'BOOKED']
                                        .includes(r.status)

                                    ? actionButton(
                                        'Hủy đăng ký sạc',
                                        'cancel_charge_request',
                                        {request_id: r.id},
                                        'danger small'
                                    )

                                    : ''}

                                ${operator &&
                                    r.status === 'PENDING'

                                    ? actionButton(
                                        'Phê duyệt đề xuất sạc',
                                        'approve_charge_request',
                                        {request_id: r.id},
                                        'small'
                                    )

                                    : ''}

                            </div>

                            ${operator &&
                                r.status === 'PENDING' ? `

                                <form
                                    class="form spaced"
                                    data-command="reject_charge_request"
                                >

                                    <input
                                        type="hidden"
                                        name="request_id"
                                        value="${esc(r.id)}"
                                    >

                                    <label>
                                        Lý do từ chối

                                        <input
                                            name="reason"
                                            required
                                            minlength="5"
                                            maxlength="500"
                                            placeholder="Giải thích lý do không thể phê duyệt yêu cầu"
                                        >
                                    </label>

                                    <button
                                        type="submit"
                                        class="danger small"
                                    >
                                        Từ chối yêu cầu sạc
                                    </button>

                                </form>

                            ` : ''}

                        </article>`;
                }).join('') : empty(
                    'Chưa có yêu cầu chỉ sạc điện',

                    operator
                        ? 'Các yêu cầu mới sẽ xuất hiện tại đây để xét duyệt.'
                        : 'Gửi yêu cầu sạc để nhận phương án cấp phát được nhân viên điều hành xác nhận.'
                )}

            </div>

        </section>`;
}


function rentalQrButton(hold) {
    return hold.owner_id === state.actor.id && hold.qr
        ? `<button
                class="secondary small"
                data-service-qr="rental"
                data-id="${esc(hold.id)}"
           >
                Xem mã QR nhận xe
           </button>`
        : '';
}

const serviceQrDialog=document.querySelector('#service-qr-dialog');
let serviceQrSelection=null, serviceQrVersion=0, serviceQrTimer;
const serviceQrMessages = {
    'Valid for a pickup request. Vehicle readiness will be checked again.':
        'Mã hợp lệ để yêu cầu nhận xe. Hệ thống sẽ kiểm tra lại điều kiện của phương tiện.',

    'Pickup requested; awaiting handover evidence.':
        'Đã yêu cầu nhận xe, đang chờ bằng chứng bàn giao.',

    'Already used. This code cannot start another journey.':
        'Mã đã được sử dụng và không thể mở thêm hành trình khác.',

    'Hold cancelled. This code is no longer valid.':
        'Lượt giữ xe đã bị hủy. Mã QR không còn hiệu lực.',

    'Hold expired. This code is no longer valid.':
        'Lượt giữ xe đã hết hạn. Mã QR không còn hiệu lực.',

    'This code is not valid for pickup.':
        'Mã QR không hợp lệ để nhận xe.',

    'Request arrival; physical reception and charging still require evidence.':
        'Có thể yêu cầu vào bãi. Việc tiếp nhận và sạc điện vẫn cần bằng chứng xác nhận.',

    'This code is not available for another arrival.':
        'Mã QR không thể sử dụng cho một lượt vào bãi khác.'
};

const serviceQrMessage = message =>
    serviceQrMessages[message] || message;
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
    const qrTitle = kind === 'rental'
      ? 'nhận xe'
      : 'sạc điện';

    renderQrContents(
        '#service-qr-content',
        `
            <div class="eyebrow">
                Xác nhận ${esc(qrTitle)}
            </div>

            <h2 id="service-qr-title">
                Mã QR ${esc(qrTitle)} của bạn
            </h2>

            <p class="spaced">
                ${chip(qr.status)}
                ${esc(serviceQrMessage(qr.message))}
            </p>

            ${qr.svg ? `
                <img
                    class="parking-qr-image"
                    alt="Mã QR xác nhận ${esc(qrTitle)}"
                    src="data:image/svg+xml;charset=utf-8,${encodeURIComponent(qr.svg)}"
                >
            ` : ''}

            <dl class="parking-qr-details">

                <dt>Mã đặt chỗ</dt>
                <dd>${esc(id)}</dd>

                <dt>Phương tiện</dt>
                <dd>${esc(vehicleName(record?.vehicle_id))}</dd>

                <dt>Trạm</dt>
                <dd>
                    ${esc(hubName(
                        record?.hub_id || record?.pickup_hub_id
                    ))}
                </dd>

                ${right ? `

                    <dt>Ô đỗ có sạc</dt>
                    <dd>${esc(right.spot_id)}</dd>

                    <dt>Cổng sạc</dt>
                    <dd>${esc(record.port_id)}</dd>

                    <dt>Khung giờ sạc</dt>
                    <dd>
                        ${date(record.scheduled_start)}
                        →
                        ${date(record.scheduled_end)}
                    </dd>

                ` : ''}

                <dt>Mã có hiệu lực đến</dt>
                <dd>${date(qr.expires_at)}</dd>

            </dl>

            <label>
                Mã xác nhận
                <input readonly value="${esc(qr.token)}">
            </label>

            <p class="muted small-text spaced">
                Xuất trình mã QR tại trạm hoặc ô đỗ được chỉ định.
                Trạng thái đặt chỗ sẽ tự động cập nhật
                sau khi được xác minh.
            </p>
        `
    );
    serviceQrTimer=setTimeout(loadServiceQr,5000);
  } catch(error) {
    if(version!==serviceQrVersion||!serviceQrDialog.open) return;
    renderQrContents(
        '#service-qr-content',
        `<h2 id="service-qr-title">
            Mã QR không khả dụng
        </h2>
        <p class="spaced">
            ${esc(apiErrorText(error))}
        </p>`
    );
  }
}
async function showServiceQr(kind,id) {
  serviceQrSelection={kind,id};
  document.querySelector('#service-qr-feedback').hidden=true;
  renderQrContents(
      '#service-qr-content',
      '<h2 id="service-qr-title">Đang tải mã QR xác nhận…</h2>'
  );
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
    fields:Array.from(form.elements).filter(el=>el.name).map(el=>({name:el.name,type: el.type,value:el.value,checked:el.checked})),
    focus:form.contains(active)?active.name:null,
    selection:form.contains(active)&&typeof active.selectionStart==='number'?[active.selectionStart,active.selectionEnd]:null,
  }));
}
function restoreFormDrafts(drafts) {
  for(const draft of drafts) {
    const form=Array.from(app.querySelectorAll('form')).find(item=>formDraftKey(item)===draft.key);
    if(!form) continue;
    if(draft.dirty) form.dataset.dirty=draft.dirty;
    for (const field of draft.fields) {
        const isChoice =
            field.type === 'checkbox' ||
            field.type === 'radio';

        const el = isChoice
            ? Array.from(form.elements).find(item =>
                item.name === field.name &&
                item.type === field.type &&
                item.value === field.value
            )
            : form.elements.namedItem(field.name);

        if (!el) continue;

        if (isChoice) {
            el.checked = field.checked;
            continue;
        }

        if (el.tagName === 'SELECT') {
            if (
                Array.from(el.options).some(
                    option => option.value === field.value
                )
            ) {
                el.value = field.value;
            }
        } else if (
            el instanceof HTMLInputElement ||
            el instanceof HTMLTextAreaElement
        ) {
            if (el.type !== 'hidden') {
                el.value = field.value;
            }
        }
    }
    if (form.dataset.command === 'd_update_incident') syncRepairConfirmation(form);
    const focus = draft.focus
      ? Array.from(form.elements).find(
          el => el.name === draft.focus
      )
      : null;
    if(focus) {focus.focus({preventScroll:true});if(draft.selection) focus.setSelectionRange(...draft.selection);}
  }
}

function notifyServiceTransitions(previous, next) {
    if (
        next.actor.role !== 'student' ||
        pending()
    ) return;

    const changes = [];

    for (const key of [
        'holds',
        'trips',
        'rights',
        'visits',
        'sessions',
        'charge_requests'
    ]) {

        const old = new Map(
            (previous[key] || []).map(
                record => [record.id, record.status]
            )
        );

        for (const record of next[key] || []) {

            if (
                old.has(record.id) &&
                old.get(record.id) !== record.status
            ) {

                changes.push(
                    `${record.id}: ${statusName(record.status)}`
                );

            }

        }

    }

    if (changes.length) {

        showNotice(
            `Cập nhật dịch vụ — ${
                changes.slice(0, 3).join('; ')
            }${changes.length > 3 ? ' …' : ''}`
        );

    }
}


const iotEventLabels = {
    PLUG: 'Kết nối cổng sạc',
    UNPLUG: 'Ngắt kết nối cổng sạc',
    DEPARTURE: 'Xác nhận rời bãi',
    RETURN_PREPARE: 'Chuẩn bị trả xe',
    RETURN: 'Xác nhận trả xe'
};

const iotEventName = kind =>
    iotEventLabels[kind] || title(kind);

function technicalSimulator() {
    if (
        state.actor.role !== 'operator' ||
        !state.simulator
    ) {
        return empty(
            'Trình mô phỏng không khả dụng'
        );
    }

    const records = [
        ...list('trips'),
        ...list('sessions'),
        ...list('visits')
    ];

    return heading(
        'Môi trường mô phỏng kỹ thuật',
        'Mô phỏng sự kiện thiết bị',
        'Các sự kiện giả lập được sử dụng để kiểm thử ranh giới tích hợp với Module D. Không kết nối với thiết bị vật lý.'
    ) +

    `<div class="grid two">

        <section class="card">

            <div class="card-body">

                <h2>Mô phỏng đầu đọc QR</h2>

                <p class="muted small-text spaced">

                    Nhập mã QR do sinh viên xuất trình
                    và vị trí đầu đọc.

                    Một lượt quét hợp lệ sẽ tạo lệnh
                    bàn giao đang chờ xác nhận.

                    Thực hiện xác nhận ACK mô phỏng
                    tại trang Điều hành.

                </p>

                <form
                    class="form spaced"
                    data-command="sim_iot_scan"
                >

                    <label>
                        Mã xác nhận QR

                        <input
                            name="qr_token"
                            required
                            autocomplete="off"
                            spellcheck="false"
                        >

                    </label>

                    <label>
                        Phương tiện được ghi nhận

                        <select name="vehicle_id" required>

                            ${list('vehicles').map(v =>
                                option(
                                    v.id,
                                    vehicleName(v.id)
                                )
                            ).join('')}

                        </select>

                    </label>

                    <label>
                        Trạm đặt đầu đọc

                        <select name="hub_id" required>

                            ${hubOptions()}

                        </select>

                    </label>

                    <label>
                        Ô đỗ đặt đầu đọc

                        <select name="spot_id" required>

                            ${list('spots').map(s =>
                                option(
                                    s.id,
                                    `${s.id} · ${hubName(s.hub_id)}`
                                )
                            ).join('')}

                        </select>

                    </label>

                    <button type="submit">

                        Mô phỏng quét QR

                    </button>

                </form>

            </div>

        </section>

        <section class="card">

            <div class="card-body">

                <h2>Mô phỏng bằng chứng thiết bị</h2>

                <p class="muted small-text spaced">

                    Sự kiện chuẩn bị trả xe cấp phát phương án
                    tiếp nhận nhưng không xác nhận phương tiện
                    đã đến trạm.

                    Các sự kiện khác gửi bằng chứng mô phỏng
                    cho hồ sơ dịch vụ và vị trí được chọn.

                </p>

                <form
                    class="form spaced"
                    data-command="sim_iot_event"
                >

                    <label>
                        Loại sự kiện

                        <select name="kind" required>

                            ${[
                                'PLUG',
                                'UNPLUG',
                                'DEPARTURE',
                                'RETURN_PREPARE',
                                'RETURN'
                            ].map(k =>
                                option(
                                    k,
                                    iotEventName(k)
                                )
                            ).join('')}

                        </select>

                    </label>

                    <label>
                        Hồ sơ liên quan

                        <select name="record_id" required>

                            ${option(
                                '',
                                'Chọn phiên sạc, lượt đỗ hoặc hành trình'
                            )}

                            ${records.map(r =>
                                option(
                                    r.id,
                                    `${r.id} · ${r.vehicle_id} · ${statusName(r.status)}`
                                )
                            ).join('')}

                        </select>

                    </label>

                    <label>
                        Phương tiện được ghi nhận

                        <select name="vehicle_id" required>

                            ${list('vehicles').map(v =>
                                option(
                                    v.id,
                                    vehicleName(v.id)
                                )
                            ).join('')}

                        </select>

                    </label>

                    <label>
                        Trạm được ghi nhận

                        <select name="hub_id" required>

                            ${hubOptions()}

                        </select>

                    </label>

                    <label>
                        Ô đỗ được ghi nhận
                        (chỉ không bắt buộc khi chuẩn bị trả xe)

                        <select name="spot_id">

                            ${option(
                                '',
                                'Chưa có ô đỗ'
                            )}

                            ${list('spots').map(s =>
                                option(
                                    s.id,
                                    `${s.id} · ${hubName(s.hub_id)}`
                                )
                            ).join('')}

                        </select>

                    </label>

                    <label>
                        Cổng sạc
                        (kết nối / ngắt kết nối)

                        <select name="port_id">

                            ${option(
                                '',
                                'Không phải sự kiện sạc'
                            )}

                            ${list('ports').map(p =>
                                option(
                                    p.id,
                                    `${p.id} · ${p.spot_id}`
                                )
                            ).join('')}

                        </select>

                    </label>

                    <button type="submit">

                        Gửi sự kiện mô phỏng

                    </button>

                </form>

            </div>

        </section>

    </div>

    <button
        class="link spaced"
        data-tab="operations"
    >

        Xem các lệnh thiết bị đang chờ →

    </button>`;
}
