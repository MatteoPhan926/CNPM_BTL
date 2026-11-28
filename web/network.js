'use strict';

const fleetSections = [
    {
        id: 'network',
        label: 'Mạng lưới',
        roles: ['operator'],
        view: networkStatus
    },
    {
        id: 'transfers',
        label: 'Điều chuyển xe',
        roles: ['operator', 'dispatcher'],
        view: transferDesk
    },
    {
        id: 'tickets',
        label: 'Bảo trì',
        roles: ['operator', 'technician'],
        view: maintenanceDesk
    },
    {
        id: 'forecast',
        label: 'Dự báo nhu cầu',
        roles: ['operator'],
        view: demandForecast
    },
    {
        id: 'telemetry',
        label: 'Dữ liệu thiết bị',
        roles: ['operator'],
        view: telemetryDesk
    }
];

let fleetSection = location.hash.slice(1).split('/')[1] || '';
let resourceHub = '';
let transferSource = '';

function fleetWorkspace() {
    const sections = fleetSections.filter(
        item => item.roles.includes(state.actor.role)
    );

    const current =
        sections.find(item => item.id === fleetSection) || sections[0];

    return heading(
        'Quản lý vận hành',
        'Quản lý xe và tài nguyên',
        {
            operator: 'Theo dõi sức chứa của các trạm, điều phối nhân viên và xem dữ liệu quan sát phương tiện.',
            dispatcher: 'Tiếp nhận các phương tiện được phân công và ghi nhận việc bàn giao tại trạm đích.',
            technician: 'Xem các phiếu bảo trì được phân công và ghi nhận kết quả kiểm tra.'
        }[state.actor.role]
    ) +
        `<div id="fleet-workspace"><nav class="fleet-sections" aria-label="Công cụ quản lý đội xe">${
            sections.map(item =>
                `<button class="${current === item ? '' : 'secondary'} small" data-fleet-section="${item.id}" ${current === item ? 'aria-current="page"' : ''}>${item.label}</button>`
            ).join('')
        }</nav>${current.view()}</div>`;
}

const fleetResources = () => [
    ...list('ports').map(item => ({
        ...item,
        type: 'Charging port'
    })),
    ...list('spots').map(item => ({
        ...item,
        type: 'Parking bay'
    })),
    ...list('vehicles').map(item => ({
        ...item,
        type: 'Vehicle'
    }))
];

// Chỉ dịch nhãn; giữ resource.type nguyên bản cho logic vị trí và SOC.
const resourceTypeLabels = {
    'Charging port': 'Cổng sạc',
    'Parking bay': 'Ô đỗ xe',
    'Vehicle': 'Phương tiện'
};

const resourceTypeName = type =>
    resourceTypeLabels[type] || type;

const telemetryAlertLabels = {
    LOW_BATTERY: 'Pin yếu',
    OVERSPEED: 'Vượt ngưỡng tốc độ',
    RAPID_DRAIN: 'Pin giảm nhanh',
    THERMAL_SPIKE: 'Nhiệt độ tăng đột biến',
    CAPACITY_WARNING: 'Cảnh báo sức chứa',
    CAPACITY_RESTRICTED: 'Hạn chế tiếp nhận',
    CAPACITY_HIGH: 'Mức sử dụng sức chứa cao'
};

const telemetryAlertName = code =>
    telemetryAlertLabels[code] || title(code);


function networkStatus() {
    const resources = fleetResources();

    const selected =
        resourceHub || list('hubs')[0]?.id || '';

    const filtered = selected === 'all'
        ? resources
        : resources.filter(r => r.hub_id === selected);

    return `<div class="grid">${
        list('hubs').map(h => {
            const stale = resources.filter(
                r =>
                    r.hub_id === h.id &&
                    r.freshness !== 'FRESH'
            ).length;

            return `<article class="record"><div class="record-main"><h2>${esc(hubName(h.id))}</h2>${chip(h.level)}</div>
      <div class="record-meta"><span>${h.available} / ${h.capacity} ô đỗ khả dụng</span><span>${h.effective_percent}% sức chứa đã cam kết</span></div>
      <p class="small-text">${
                stale
                    ? esc(stale) + ' tài nguyên đang chờ dữ liệu mới'
                    : 'Dữ liệu quan sát tài nguyên còn mới'
            }</p>
      <button class="link spaced" data-resource-hub="${esc(h.id)}">Xem tài nguyên →</button></article>`;
        }).join('')
    }</div>
  <div class="section-heading"><h2>Danh sách tài nguyên</h2><label>Vị trí<select data-resource-filter>${
        option('all', 'Tất cả vị trí', selected === 'all')
    }${
        list('hubs').map(h =>
            option(h.id, hubName(h.id), h.id === selected)
        ).join('')
    }</select></label></div>
  <div class="table-wrap"><table><thead><tr><th>Tài nguyên</th><th>Vị trí / Ô đỗ</th><th>Pin</th><th>Tình trạng kỹ thuật</th><th>Dữ liệu quan sát</th><th>Quản lý khả dụng</th></tr></thead><tbody>${
        filtered.map(r =>
            `<tr><td><strong>${esc(r.id)}</strong><br>${esc(resourceTypeName(r.type))}</td><td>${resourceLocation(r)}</td><td>${resourceBattery(r)}</td><td>${chip(r.health)}</td><td>${chip(r.freshness)}<br>${date(r.observed_at)}</td><td>${
                ['OPERABLE', 'DEACTIVATED'].includes(r.health) &&
                !r.maintenance_ticket_id
                    ? actionButton(
                        r.health === 'DEACTIVATED'
                            ? 'Kích hoạt lại'
                            : 'Vô hiệu hóa',
                        'd_resource_state',
                        {
                            resource_id: r.id,
                            active: r.health === 'DEACTIVATED'
                        },
                        'secondary small'
                    )
                    : 'Đang bảo trì'
            }</td></tr>`
        ).join('')
    }</tbody></table></div>`;
}


function vehicleChecks(ids, labelFor) {
    return ids.map(id =>
        `<label class="check-label"><input name="vehicle_ids" type="checkbox" value="${esc(id)}">${esc(labelFor(id))}</label>`
    ).join('');
}


function transferFields() {
    const source = transferSource || list('hubs')[0]?.id;

    const vehicles = list('vehicles').filter(
        v =>
            v.hub_id === source &&
            v.kind === 'shared' &&
            v.transferable
    );

    const destinations = list('hubs').filter(
        h => h.id !== source
    );

    return `<div class="form-row"><label>Trạm xuất phát<select name="source_hub_id" data-transfer-source required>${
        list('hubs').map(h =>
            option(h.id, hubName(h.id), h.id === source)
        ).join('')
    }</select></label>
    <label>Trạm đích<select name="dest_hub_id" required>${
        destinations.map(h =>
            option(h.id, hubName(h.id))
        ).join('')
    }</select></label></div>
    <fieldset class="vehicle-checks"><legend>Xe dùng chung đủ điều kiện điều chuyển</legend>${
        vehicles.length
            ? vehicleChecks(
                vehicles.map(v => v.id),
                id => id
            )
            : '<p class="muted">Không có phương tiện đủ điều kiện tại trạm này.</p>'
    }</fieldset>
    <label class="check-label"><input type="checkbox" name="charging_bays">Giữ ô đỗ có sạc tại trạm đích</label>
    <label>Nhân viên được phân công<select name="staff_id">${
        option('dispatcher', 'Nhân viên điều phối')
    }</select></label>
    <button type="submit" ${
        vehicles.length && destinations.length
            ? ''
            : 'disabled'
    }>Xem trước phương án điều chuyển</button>`;
}


function transferOrder(order) {
    const operator = state.actor.role === 'operator';

    const delivered = order.delivered;
    const pendingIds = order.pending;

    const remaining = order.vehicle_ids.filter(
        id =>
            !delivered.includes(id) &&
            !pendingIds.includes(id)
    );

    let controls = '';

    if (operator && order.status === 'DRAFT') {
        controls = actionButton(
            'Phát hành lệnh điều chuyển',
            'transfer_issue',
            { order_id: order.id },
            'small'
        );

    } else if (!operator && order.status === 'ISSUED') {
        controls = actionButton(
            'Bắt đầu điều chuyển',
            'transfer_start',
            { order_id: order.id },
            'small'
        );

    } else if (
        !operator &&
        order.status === 'IN_PROGRESS' &&
        remaining.length
    ) {
        controls = `<form class="form" data-command="transfer_handover"><input type="hidden" name="order_id" value="${esc(order.id)}">
      <fieldset class="vehicle-checks"><legend>Phương tiện được đưa đến trạm đích</legend>${vehicleChecks(remaining, id => id)}</fieldset><button type="submit">Yêu cầu bàn giao</button></form>`;
    }

    return `<article class="record"><div class="record-main"><div><h3>${esc(hubName(order.source_hub_id))} → ${esc(hubName(order.dest_hub_id))}</h3><span class="record-id">${esc(order.id)}</span></div>${chip(order.status)}</div>
    <div class="record-meta"><span>Phân công cho ${esc(order.staff_id)}</span><span>Đã bàn giao ${delivered.length} / ${order.vehicle_ids.length} xe</span></div>
    <p class="small-text">Phương tiện · ${esc(order.vehicle_ids.join(', '))}${
        order.charging_bays
            ? ' · Có yêu cầu ô đỗ sạc'
            : ''
    }</p>
    ${
        delivered.length
            ? `<p class="small-text">Đã bàn giao · ${esc(delivered.join(', '))}</p>`
            : ''
    }
    ${
        pendingIds.length
            ? `<p class="record-note">Đang chờ bằng chứng · ${esc(pendingIds.join(', '))}${
                operator
                    ? ' <button class="link" data-tab="operations">Mở danh sách lệnh thiết bị →</button>'
                    : ''
            }</p>`
            : ''
    }
    ${
        controls
            ? `<div class="record-actions">${controls}</div>`
            : ''
    }</article>`;
}


function transferDesk() {
    const operator = state.actor.role === 'operator';
    const orders = list('orders').slice().reverse();

    const listing = `<section><div class="section-heading"><h2>${
        operator
            ? 'Lệnh điều chuyển'
            : 'Lệnh điều chuyển được phân công'
    }</h2></div><div class="records">${
        orders.length
            ? orders.map(transferOrder).join('')
            : empty(
                'Chưa có lệnh điều chuyển',
                operator
                    ? 'Xem trước phương án điều chuyển để tạo bản nháp.'
                    : 'Các lệnh đã phát hành và được phân công cho bạn sẽ xuất hiện tại đây.'
            )
    }</div></section>`;

    if (!operator) return listing;

    return `<div class="split">${listing}<section class="card"><div class="card-body"><h2>Lập kế hoạch điều chuyển</h2><form class="form spaced" data-command="transfer_preview">${transferFields()}</form></div></section></div>`;
}


function maintenanceTicket(ticket) {
    const isAssigned =
        state.actor.role === 'technician' &&
        ticket.technician_id === state.actor.id;

    return `<article class="record"><div class="record-main"><div><h3>${esc(ticket.resource_id)}</h3><span class="record-id">${esc(ticket.id)}</span></div>${chip(ticket.status)}</div>
    <p class="spaced">${esc(ticket.message)}</p><div class="record-meta"><span>Phân công cho ${esc(ticket.technician_id)}</span>${
        ticket.origin_incident_id
            ? `<span>Báo cáo liên quan · ${esc(ticket.origin_incident_id)}</span>`
            : ''
    }</div>
    ${
        ticket.response
            ? `<p class="record-note">${esc(ticket.response)}</p>`
            : ''
    }
    ${
        isAssigned && ticket.status === 'OPEN'
            ? `<form class="form spaced" data-command="d_update_incident">
      <input type="hidden" name="incident_id" value="${esc(ticket.id)}">
      <label>Kết quả kiểm tra<select name="outcome"><option value="ESCALATED_WORKSHOP">Chuyển đến xưởng sửa chữa</option><option value="RESOLVED">Khắc phục và khôi phục dịch vụ</option></select></label>
      <label>Ghi chú kiểm tra<textarea name="note" required minlength="5" maxlength="1000"></textarea></label>
      <label class="check-label" hidden><input type="checkbox" name="safety_passed">Tôi đã hoàn thành kiểm tra an toàn và tài nguyên đạt yêu cầu.</label>
      <button type="submit">Ghi nhận kết quả</button></form>`
            : ''
    }</article>`;
}


function maintenanceDesk() {
    const incidents = list('incidents');

    const tickets = incidents
        .filter(row => row.kind === 'MAINTENANCE')
        .slice()
        .reverse();

    const listing = `<section><div class="section-heading"><h2>Danh sách phiếu bảo trì</h2></div><div class="records">${
        tickets.length
            ? tickets.map(maintenanceTicket).join('')
            : empty('Chưa có phiếu bảo trì')
    }</div></section>`;

    if (state.actor.role !== 'operator') return listing;

    const resources = fleetResources().filter(
        r => !r.maintenance_ticket_id
    );

    const reports = incidents.filter(
        i =>
            i.kind !== 'MAINTENANCE' &&
            ['OPEN', 'WAITING_FOR_D'].includes(i.status) &&
            !i.maintenance_ticket_id
    );

    return `<div class="split">${listing}<section class="card"><div class="card-body"><h2>Tạo phiếu bảo trì</h2>
    <p class="muted small-text spaced">Tạo phiếu sẽ cách ly tài nguyên khỏi hoạt động và phân công cho kỹ thuật viên.</p><form class="form spaced" data-command="d_open_incident">
    <label>Tài nguyên gặp sự cố<select name="resource_id" required>${
        option('', 'Chọn tài nguyên')
    }${
        resources.map(r =>
            option(
                r.id,
                `${r.id} · ${resourceTypeName(r.type)}`
            )
        ).join('')
    }</select></label>
    <label>Báo cáo liên quan (không bắt buộc)<select name="origin_incident_id">${
        option('', 'Kiểm tra trực tiếp')
    }${
        reports.map(i =>
            option(i.id, `${i.id} · ${i.message}`)
        ).join('')
    }</select></label>
    <label>Mô tả sự cố<textarea name="message" required minlength="5" maxlength="1000"></textarea></label><button type="submit">Tạo phiếu bảo trì</button></form></div></section></div>`;
}


function demandForecast() {
    const scenarios = list('scenarios').slice().reverse();

    return `<div class="split"><section><div class="section-heading"><h2>Kịch bản nhu cầu</h2></div><div class="records">${
        scenarios.length
            ? scenarios.map(s =>
                `<article class="record"><h3>${esc(hubName(s.hub_id))} · ${esc(s.demand_factor)}× nhu cầu</h3><span class="record-id">${esc(s.id)}</span>
    <div class="table-wrap spaced"><table><thead><tr><th>Trạm</th><th>Mức sử dụng hiện tại</th><th>Mức sử dụng dự báo</th></tr></thead><tbody>${
                    s.impact.map(h =>
                        `<tr><td>${esc(hubName(h.hub_id))}</td><td>${esc(h.current_percent)}%</td><td>${esc(h.projected_percent)}%</td></tr>`
                    ).join('')
                }</tbody></table></div>
    ${
                    s.recommendations.length
                        ? s.recommendations.map((r, i) =>
                            `<div class="record-note"><p>${esc(hubName(r.source_hub_id))} → ${esc(hubName(r.dest_hub_id))} · ${esc(r.vehicle_ids.join(', '))}</p><div class="record-actions">${
                                actionButton(
                                    'Tạo bản nháp điều chuyển',
                                    'what_if_draft',
                                    {
                                        scenario_id: s.id,
                                        recommendation_index: i
                                    },
                                    'secondary small'
                                )
                            }</div></div>`
                        ).join('')
                        : '<p class="record-note">Không có đề xuất điều chuyển cho kịch bản này.</p>'
                }</article>`
            ).join('')
            : empty('Chưa có dự báo')
    }</div></section>
    <section class="card"><div class="card-body"><h2>Mô phỏng thay đổi nhu cầu</h2><form class="form spaced" data-command="what_if">
      <label>Trạm mục tiêu<select name="hub_id" required>${hubOptions()}</select></label><label>Hệ số nhu cầu<input type="number" min="0.5" max="3" step="0.1" name="demand_factor" value="1.5" required></label><button type="submit">Chạy dự báo</button>
      <p class="form-help">Xem xét mức sử dụng dự báo trước khi tạo lệnh điều chuyển.</p></form></div></section></div>`;
}


function telemetryRows(vehicles) {
    const packets = vehicles
        .map(v => v.last_telemetry)
        .filter(Boolean)
        .sort((a, b) => b.observed_at - a.observed_at);

    return packets.length
        ? `<div class="records">${
            packets.map(p =>
                `<article class="record"><div class="record-main"><h3>${esc(p.resourceId)}</h3>${chip('SIMULATED')}</div>
    <div class="record-meta"><span>${date(p.observed_at)}</span><span>Gói tin ${esc(p.sequence)}</span></div>
    <p>${esc(p.batterySoc)}% pin${
                    p.speed != null
                        ? ' · ' + esc(p.speed) + ' km/h'
                        : ''
                }${
                    p.temperatureC != null
                        ? ' · ' + esc(p.temperatureC) + ' °C'
                        : ''
                }</p>
    ${
                    p.destinationHubId
                        ? `<p class="small-text">Trạm đích · ${esc(hubName(p.destinationHubId))}</p>`
                        : ''
                }
    ${
                    p.alerts?.length
                        ? `<div class="record-note">${
                            esc(
                                p.alerts
                                    .map(telemetryAlertName)
                                    .join(' · ')
                            )
                        }</div>`
                        : ''
                }</article>`
            ).join('')
        }</div>`
        : empty('Chưa nhận được dữ liệu phương tiện');
}


function telemetryDesk() {
    const vehicles = list('vehicles');

    const listing = `<section><div class="section-heading"><h2>Dữ liệu phương tiện mới nhất</h2>
    <label class="check-label"><input type="checkbox" id="live-telemetry" checked>Cập nhật trực tiếp</label></div>
    <div id="telemetry-readings">${telemetryRows(vehicles)}</div></section>`;

    if (!state.simulator) return listing;

    return `<div class="split">${listing}<section class="sim-area"><h2>Mô phỏng dữ liệu phương tiện</h2>
    <form class="form spaced" data-command="d_telemetry"><label>Phương tiện<select name="resourceId" required>${
        vehicles.map(v =>
            option(v.id, v.id)
        ).join('')
    }</select></label>
    <label>Mức pin (%)<input type="number" min="0" max="100" step="0.1" name="batterySoc" value="65" required></label>
    <div class="form-row"><label>Tốc độ (km/h)<input type="number" min="0" step="0.1" max="500" name="speed" value="0"></label><label>Nhiệt độ (°C)<input type="number" step="0.1" min="-80" max="250" name="temperatureC" value="27"></label></div>
    <label>Trạm đích (không bắt buộc)<select name="destinationHubId">${
        option('', 'Không có trạm đích')
    }${
        list('hubs').map(h =>
            option(h.id, hubName(h.id))
        ).join('')
    }</select></label>
    <button type="submit">Gửi dữ liệu mô phỏng</button></form></section></div>`;
}


function prepareFleetCommand(form, values, payload) {
    if (form.elements.vehicle_ids) {
        payload.vehicle_ids = values.getAll('vehicle_ids');

        if (!payload.vehicle_ids.length) {
            showNotice(
                'Vui lòng chọn ít nhất một phương tiện để điều chuyển.',
                true
            );

            return false;
        }
    }

    if (form.elements.charging_bays)
        payload.charging_bays = form.elements.charging_bays.checked;

    if (form.elements.safety_passed)
        payload.safety_passed = form.elements.safety_passed.checked;

    for (const field of [
        'demand_factor',
        'batterySoc',
        'speed',
        'temperatureC'
    ]) {
        if (
            payload[field] !== undefined &&
            payload[field] !== ''
        )
            payload[field] = Number(payload[field]);
    }

    for (const field of [
        'origin_incident_id',
        'destinationHubId',
        'speed',
        'temperatureC'
    ]) {
        if (payload[field] === '')
            delete payload[field];
    }

    if (form.dataset.command === 'd_telemetry')
        payload.event_id = crypto.randomUUID();

    return true;
}


document.addEventListener('click', event => {
    const target = event.target.closest(
        '#fleet-workspace button'
    );

    if (!target) return;

    if (target.dataset.fleetSection) {
        fleetSection = target.dataset.fleetSection;

        window.history.replaceState(
            null,
            '',
            '#network/' + fleetSection
        );

        render();

    } else if (target.dataset.resourceHub) {
        resourceHub = target.dataset.resourceHub;

        render();

        document
            .querySelector('[data-resource-filter]')
            ?.focus();
    }
});


function syncRepairConfirmation(form) {
    const check = form.elements.safety_passed;
    check.required = form.elements.outcome.value === 'RESOLVED';
    check.closest('label').hidden = !check.required;
    if (!check.required) check.checked = false;
}

document.addEventListener('change', event => {
    const input = event.target;

    if (!input.closest('#fleet-workspace')) return;

    if (input.matches('[data-resource-filter]')) {
        resourceHub = input.value;

        render();

        document
            .querySelector('[data-resource-filter]')
            ?.focus();

    } else if (input.matches('[data-transfer-source]')) {
        transferSource = input.value;

        input.form.innerHTML = transferFields();

        document
            .querySelector('[data-transfer-source]')
            ?.focus();

    } else if (input.matches('form[data-command="d_update_incident"] [name="outcome"]')) {
        syncRepairConfirmation(input.form);
    }
});


// Update the packet list in place so an operator can finish entering a reading.
let readingTelemetry = false;

setInterval(async () => {
    const panel = document.getElementById(
        'telemetry-readings'
    );

    if (
        !panel ||
        document.hidden ||
        !document.getElementById('live-telemetry')?.checked ||
        busy ||
        readingTelemetry
    ) return;

    readingTelemetry = true;

    try {
        const snapshot = await request('/api/state');

        if (
            panel.isConnected &&
            !busy &&
            snapshot.actor.role === 'operator'
        ) {
            panel.innerHTML = telemetryRows(snapshot.vehicles);
        }

    } catch (error) {
        if (panel.isConnected) {
            document.getElementById('live-telemetry').checked = false;

            if (error.status === 401) {
                state = null;
                renderLogin();

            } else
                showNotice(
                    'Đã tạm dừng cập nhật dữ liệu trực tiếp. ' +
                    apiErrorText(error),
                    true
                );
        }

    } finally {
        readingTelemetry = false;
    }
}, 5000);


function resourceLocation(resource) {
    const spotId = resource.type === 'Parking bay'
        ? resource.id
        : resource.spot_id;

    return `
        ${esc(hubName(resource.hub_id))}
        <br>
        <span class="muted small-text">
            ${spotId ? esc(spotId) : 'Chưa được gán ô đỗ'}
        </span>
    `;
}


function resourceBattery(resource) {
    if (
        resource.type !== 'Vehicle' ||
        resource.soc == null
    ) {
        return '—';
    }

    return `
        <span class="battery">
            ▰ ${esc(resource.soc)}%
        </span>
    `;
}