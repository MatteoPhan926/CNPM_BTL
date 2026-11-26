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
  ['overview', '◈', 'Khám phá trạm'],
  ['journeys', '↗', 'Hành trình của tôi'],
  ['parking', '▦', 'Đỗ xe'],
  ['charging', 'ϟ', 'Sạc điện'],
  ['support', '◎', 'Hỗ trợ'],
  ['operations', '≋', 'Điều hành'],
  ['technical', 'T', 'Mô phỏng thiết bị'],
  ['network', '⇄', 'Quản lý đội xe'],
  ['history', '◷', 'Lịch sử hoạt động']
];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const list = key => Array.isArray(state?.[key]) ? state[key] : [];
const find = (key, id) => list(key).find(row => row.id === id);
const title = value => String(value || '').replaceAll('_', ' ').toLowerCase().replace(/^./, c => c.toUpperCase());
const roleLabels = {
    student: 'Sinh viên',
    operator: 'Nhân viên điều hành',
    dispatcher: 'Nhân viên điều phối',
    technician: 'Kỹ thuật viên'
};

const roleName = role =>
    roleLabels[role] || title(role);
const date = value => value
    ? new Date(value * 1000).toLocaleString('vi-VN', {
        day: '2-digit',
        month: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false
    })
    : '—';
const inputDate = value => { const d = new Date(value * 1000); return new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0,16); };
const now = () => state?.now || Date.now()/1000;
const hubLabels = {
    H1: 'Trạm Metro',
    H2: 'Trạm trường đại học',
    H3: 'Trạm ký túc xá'
};

const hubName = id =>
    hubLabels[id] ||
    find('hubs', id)?.name ||
    id ||
    'Đang di chuyển';
const vehicleName = id => {
    const v = find('vehicles', id);

    return v
        ? `${v.label || v.id} · ${
            v.kind === 'shared'
                ? 'Dùng chung'
                : 'Cá nhân'
        }`
        : id;
};
const statusClass = status => /PENDING|UNKNOWN|STALE|WARNING|RESERVED|BOOKED|PROPOSED|WAIT|DRAFT|ASSISTANCE/i.test(status) ? 'warn' : /FAULT|REJECT|OUT_OF_SERVICE|EXPIRED|CANCEL|CLOSED_UNFULFILLED/i.test(status) ? 'bad' : /ACTIVE|AVAILABLE|CONFIRM|OPEN|CLOSED|COMPLETED|ACK|APPLIED|OPERABLE|EMPTY|UNPLUGGED/i.test(status) ? 'good' : 'neutral';
const statusLabels = {
    OPEN: 'Đang mở',
    CLOSED: 'Đã đóng',

    AVAILABLE: 'Khả dụng',
    UNAVAILABLE: 'Không khả dụng',

    FRESH: 'Đã cập nhật',
    STALE: 'Dữ liệu đã cũ',
    UNKNOWN: 'Chưa xác định',

    OPERABLE: 'Hoạt động bình thường',
    OUT_OF_SERVICE: 'Ngừng hoạt động',
    FAULT: 'Gặp sự cố',

    EMPTY: 'Còn trống',
    OCCUPIED: 'Đang sử dụng',
    RESERVED: 'Đã giữ chỗ',

    WARNING: 'Cảnh báo',
    HIGH: 'Mức cao',
    FULL: 'Đã đầy',

    ACTIVE: 'Đang hoạt động',
    PENDING: 'Đang chờ',
    BOOKED: 'Đã đặt',
    CONFIRMED: 'Đã xác nhận',
    COMPLETED: 'Hoàn thành',
    CANCELLED: 'Đã hủy',
    EXPIRED: 'Hết hạn',
    REJECTED: 'Bị từ chối',

    HANDOVER_PENDING: 'Chờ xác nhận bàn giao',
    CONSUMED: 'Đã sử dụng',
    ASSISTANCE_PENDING: 'Đang chờ hỗ trợ',
    PENDING_VERIFICATION: 'Đang chờ xác minh',
    ACK: 'Đã xác nhận',
    ACKNOWLEDGED: 'Đã xác nhận',

    PARKED: 'Đang đỗ xe',
    DEPARTED: 'Đã rời bãi',
    OFFERED: 'Đã đề xuất phương án',
    CLOSED_UNFULFILLED: 'Đã đóng nhưng chưa hoàn tất',

    START_PENDING: 'Chờ bắt đầu sạc',
    STOP_PENDING: 'Chờ dừng sạc',
    CHARGING: 'Đang sạc',
    PLUGGED: 'Đã kết nối',
    UNPLUGGED: 'Chưa kết nối',
    ON: 'Đang cấp điện',
    OFF: 'Đã ngắt điện',
    DRAFT: 'Bản nháp',
    PROPOSED: 'Đã đề xuất',
    PREVIEW: 'Bản xem trước',
    APPLIED: 'Đã áp dụng',
    ANOMALY: 'Bất thường',

    RESOLVED: 'Đã giải quyết',
    DECLINED: 'Đã từ chối',
    WAITING_FOR_D: 'Đang chờ bộ phận điều phối',
    ACCEPTED: 'Đã chấp nhận',

    NORMAL: 'Bình thường',
    RESTRICTED: 'Hạn chế tiếp nhận',
    DEACTIVATED: 'Đã vô hiệu hóa',

    ISSUED: 'Đã phát hành',
    IN_PROGRESS: 'Đang thực hiện',

    ESCALATED_WORKSHOP: 'Đã chuyển đến xưởng sửa chữa',

    SIMULATED: 'Dữ liệu mô phỏng',
    SAVED: 'Đã lưu',
    OK: 'Thành công',
    SUCCESS: 'Thành công',
};

const statusName = status =>
    statusLabels[String(status || '').toUpperCase()]
    || title(status);

const deviceCommandLabels = {
    PICKUP: 'Bàn giao xe cho người thuê',
    ARRIVAL: 'Tiếp nhận xe vào bãi',
    RETURN: 'Tiếp nhận xe trả',
    RETURN_PREPARE: 'Chuẩn bị tiếp nhận xe trả',
    START_CHARGE: 'Bắt đầu sạc',
    STOP_CHARGE: 'Dừng sạc',
    PLUG: 'Kết nối cổng sạc',
    UNPLUG: 'Ngắt kết nối cổng sạc',
    DEPARTURE: 'Xác nhận rời bãi'
};

const deviceCommandName = kind =>
    deviceCommandLabels[String(kind || '').toUpperCase()]
    || title(kind);

const actionLabels = {
    // Module A - Thuê xe
    reserve_vehicle: 'Giữ phương tiện',
    cancel_hold: 'Hủy giữ xe',
    select_return_hub: 'Chọn trạm trả xe',

    // Module B - Đỗ xe
    reserve_parking: 'Đặt chỗ đỗ xe',
    cancel_parking: 'Hủy quyền đỗ xe',
    register_vehicle: 'Đăng ký phương tiện',

    // Module C - Sạc điện
    submit_charge_request: 'Gửi yêu cầu sạc',
    approve_charge_request: 'Phê duyệt yêu cầu sạc',
    reject_charge_request: 'Từ chối yêu cầu sạc',
    cancel_charge_request: 'Hủy yêu cầu sạc',
    register_charge: 'Đăng ký bổ sung sạc',
    cancel_charge: 'Hủy phiên sạc',
    stop_charge: 'Dừng sạc',
    fleet_charge: 'Đăng ký sạc cho đội xe',

    // Hỗ trợ và điều hành
    support: 'Gửi yêu cầu hỗ trợ',
    capacity_plan: 'Đề xuất phương án tiếp nhận',
    accept_capacity: 'Phản hồi phương án tiếp nhận',
    schedule_preview: 'Tạo phương án lịch sạc',
    schedule_confirm: 'Xác nhận lịch sạc',

    // IoT Simulator
    simulate: 'Mô phỏng kết quả lệnh thiết bị',
    sim_refresh: 'Làm mới dữ liệu mô phỏng',
    sim_observe: 'Gửi dữ liệu quan sát mô phỏng',
    sim_iot_scan: 'Mô phỏng quét mã QR',
    sim_iot_event: 'Gửi sự kiện thiết bị',

    // Sự kiện thiết bị
    pickup: 'Xác nhận nhận xe',
    arrival: 'Xác nhận vào bãi',
    return_prepare: 'Chuẩn bị trả xe',
    return: 'Xác nhận trả xe',
    departure: 'Xác nhận rời bãi',
    plug: 'Kết nối cổng sạc',
    unplug: 'Ngắt kết nối cổng sạc',
    start_charge: 'Bắt đầu sạc',

    // Tài khoản
    login: 'Đăng nhập',
    logout: 'Đăng xuất'
};

const actionName = action =>
    actionLabels[String(action || '').toLowerCase()]
    || title(action);


const recordTypeLabels = {
    hub: 'Trạm di chuyển',
    hubs: 'Trạm di chuyển',

    vehicle: 'Phương tiện',
    vehicles: 'Phương tiện',

    spot: 'Ô đỗ xe',
    spots: 'Ô đỗ xe',

    port: 'Cổng sạc',
    ports: 'Cổng sạc',

    hold: 'Lượt giữ xe',
    holds: 'Lượt giữ xe',

    trip: 'Hành trình',
    trips: 'Hành trình',

    right: 'Quyền đỗ xe',
    rights: 'Quyền đỗ xe',

    visit: 'Lượt đỗ xe',
    visits: 'Lượt đỗ xe',

    session: 'Phiên sạc',
    sessions: 'Phiên sạc',

    charge_request: 'Yêu cầu sạc điện',
    charge_requests: 'Yêu cầu sạc điện',

    incident: 'Yêu cầu hỗ trợ',
    incidents: 'Yêu cầu hỗ trợ',

    command: 'Lệnh thiết bị',
    commands: 'Lệnh thiết bị',

    plan: 'Phương án cấp phát',
    plans: 'Phương án cấp phát',

    transfer_order: 'Lệnh điều chuyển',
    transfer_orders: 'Lệnh điều chuyển',

    maintenance_ticket: 'Phiếu bảo trì',
    maintenance_tickets: 'Phiếu bảo trì',

    telemetry: 'Dữ liệu thiết bị',

    audit: 'Bản ghi hoạt động',

    user: 'Người dùng',
    users: 'Người dùng'
};

const recordTypeName = kind =>
    recordTypeLabels[String(kind || '').toLowerCase()]
    || title(kind);


const fieldLabels = {
    // Định danh
    id: 'Mã định danh',
    name: 'Tên',
    label: 'Tên hiển thị',
    kind: 'Loại',
    type: 'Loại',
    status: 'Trạng thái',
    state: 'Trạng thái',
    role: 'Vai trò',

    // Người dùng
    owner_id: 'Chủ sở hữu',
    actor_id: 'Người thực hiện',
    user_id: 'Người dùng',
    assigned_to: 'Người được phân công',

    // Tài nguyên
    vehicle_id: 'Mã phương tiện',
    hub_id: 'Mã trạm',
    spot_id: 'Mã ô đỗ',
    port_id: 'Mã cổng sạc',
    resource_id: 'Mã tài nguyên',
    resource_type: 'Loại tài nguyên',

    // Thuê xe
    hold_id: 'Mã lượt giữ xe',
    trip_id: 'Mã hành trình',
    pickup_hub_id: 'Trạm nhận xe',
    return_hub_id: 'Trạm trả xe',
    return_right_id: 'Quyền đỗ khi trả xe',

    // Đỗ xe
    right_id: 'Mã quyền đỗ xe',
    visit_id: 'Mã lượt đỗ',
    capacity: 'Sức chứa',
    available: 'Khả dụng',
    occupied: 'Đang sử dụng',
    held: 'Đã giữ chỗ',
    unknown: 'Chưa xác định',
    level: 'Mức sử dụng',

    // Sạc điện
    request_id: 'Mã yêu cầu',
    session_id: 'Mã phiên sạc',
    soc: 'Mức pin hiện tại',
    declared_soc: 'Mức pin khai báo',
    target_soc: 'Mức pin mục tiêu',
    battery_kwh: 'Dung lượng pin (kWh)',
    energy_kwh: 'Năng lượng (kWh)',
    kw: 'Công suất (kW)',
    power_kw: 'Công suất (kW)',
    connector: 'Loại đầu nối',
    duration: 'Thời lượng (giây)',
    charging: 'Đăng ký kèm sạc',
    plug: 'Trạng thái kết nối',
    power: 'Trạng thái cấp điện',

    // Thời gian
    at: 'Thời điểm',
    start: 'Thời gian bắt đầu',
    end: 'Thời gian kết thúc',
    created_at: 'Thời gian tạo',
    updated_at: 'Cập nhật lần cuối',
    expires_at: 'Thời điểm hết hạn',
    started_at: 'Thời điểm bắt đầu',
    ended_at: 'Thời điểm kết thúc',
    observed_at: 'Thời điểm quan sát',
    arrival_time: 'Thời gian đến',
    scheduled_start: 'Lịch bắt đầu',
    scheduled_end: 'Lịch kết thúc',
    expected_collection_at: 'Thời gian nhận xe dự kiến',
    offer_expires_at: 'Hạn phản hồi phương án',

    // Điều chuyển
    transfer_order_id: 'Mã lệnh điều chuyển',
    source_hub_id: 'Trạm xuất phát',
    destination_hub_id: 'Trạm đích',
    vehicle_ids: 'Danh sách phương tiện',

    // Bảo trì và hỗ trợ
    health: 'Tình trạng kỹ thuật',
    incident_id: 'Mã yêu cầu hỗ trợ',
    ticket_id: 'Mã phiếu bảo trì',
    message: 'Nội dung',
    reason: 'Lý do',
    response: 'Phản hồi',
    rejection_reason: 'Lý do từ chối',
    offered_right_id: 'Quyền đỗ được đề xuất',
    safety_checked: 'Đã kiểm tra an toàn',

    // IoT và Telemetry
    command_id: 'Mã lệnh thiết bị',
    event_id: 'Mã sự kiện',
    record_id: 'Mã hồ sơ',
    freshness: 'Độ mới dữ liệu',
    sequence: 'Số thứ tự',
    speed_kmh: 'Tốc độ (km/h)',
    temperature_c: 'Nhiệt độ (°C)',
    simulated: 'Dữ liệu mô phỏng',
    outcome: 'Kết quả',

    // Hệ thống
    revision: 'Phiên bản dữ liệu',
    action: 'Thao tác',
    before: 'Trước thay đổi',
    after: 'Sau thay đổi'
};

const fieldName = key =>
    fieldLabels[String(key || '').toLowerCase()]
    || title(key);

const chip = status =>
    `<span class="chip ${statusClass(status)}">
        ${esc(statusName(status))}
    </span>`;
const actionButton = (label, action, payload, style='secondary small') => `<button class="${style}" data-action="${esc(action)}" data-payload="${esc(JSON.stringify(payload))}">${esc(label)}</button>`;
const option = (value, label, selected=false) => `<option value="${esc(value)}" ${selected?'selected':''}>${esc(label)}</option>`;
const empty = (heading, text='') => `<div class="empty"><strong>${esc(heading)}</strong>${esc(text)}</div>`;
const pendingKey = () => `emobility_pending_${state?.actor?.id}`;
const pending = () => {try{return JSON.parse(localStorage.getItem(pendingKey()) || 'null');}catch{return null;}};

const apiErrorLabels = {
    // Xác thực và phân quyền
    AUTH_REQUIRED: 'Vui lòng đăng nhập để tiếp tục.',
    UNAUTHORIZED: 'Yêu cầu chưa được xác thực.',
    LOGIN: 'Thông tin đăng nhập không hợp lệ.',
    FORBIDDEN: 'Bạn không có quyền thực hiện thao tác này.',
    RATE_LIMIT: 'Quá nhiều lần thử. Vui lòng thử lại sau một phút.',

    // Dữ liệu đầu vào
    INVALID_INPUT: 'Dữ liệu đầu vào không hợp lệ.',
    INVALID_STATE: 'Trạng thái hiện tại không cho phép thao tác này.',
    NOT_FOUND: 'Không tìm thấy dữ liệu.',
    UNKNOWN_ACTION: 'Thao tác không được hỗ trợ.',
    INVALID_INTENT: 'Mã yêu cầu không hợp lệ.',
    INTENT_CONFLICT: 'Mã yêu cầu đã được sử dụng cho nội dung khác.',
    EVENT_CONFLICT: 'Mã sự kiện đã được sử dụng với dữ liệu khác.',
    COMMAND: 'Thông tin lệnh không hợp lệ.',
    JSON: 'Dữ liệu JSON không hợp lệ.',
    CONTENT_TYPE: 'Định dạng dữ liệu gửi đi không được hỗ trợ.',
    BODY_SIZE: 'Kích thước dữ liệu yêu cầu không hợp lệ.',
    ORIGIN: 'Nguồn gửi yêu cầu không hợp lệ.',
    HOST: 'Địa chỉ máy chủ không hợp lệ.',

    // Thuê xe
    ACTIVE_JOURNEY: 'Bạn đang có lượt giữ xe hoặc hành trình chưa kết thúc.',
    HOLD_EXPIRED: 'Lượt giữ xe không còn hiệu lực.',
    INVALID_HOLD: 'Lượt giữ xe không phù hợp với phương tiện.',
    HANDOVER_PENDING: 'Không thể thay đổi yêu cầu bàn giao ở trạng thái hiện tại.',
    VEHICLE_UNAVAILABLE: 'Phương tiện hiện không khả dụng.',
    VEHICLE_CLAIMED: 'Phương tiện đã được giữ cho nghiệp vụ khác.',
    UNSAFE_PICKUP: 'Phương tiện không còn đủ điều kiện bàn giao.',
    TRIP_CLOSED: 'Hành trình đã kết thúc.',
    USE_PICKUP: 'Xe dùng chung phải thực hiện quy trình nhận xe.',
    USE_RETURN: 'Xe dùng chung phải thực hiện quy trình trả xe.',

    // Đỗ xe và sức chứa
    HUB_CAPACITY: 'Trạm không còn sức chứa tiếp nhận thông thường.',
    HUB_CLOSED: 'Trạm đã đóng đối với yêu cầu cấp phát mới.',
    NO_SPOT: 'Không có ô đỗ trống phù hợp với dữ liệu còn mới.',
    ALREADY_PARKED: 'Phương tiện đã được đỗ trong bãi.',
    PARKING_IN_USE: 'Không thể hủy quyền đỗ xe ở trạng thái hiện tại.',
    VEHICLE_PARKING_CONFLICT: 'Phương tiện có lượt đặt chỗ đỗ bị trùng thời gian.',
    INVALID_WINDOW: 'Khung thời gian đăng ký không hợp lệ.',
    INVALID_RIGHT: 'Quyền đỗ xe không hợp lệ.',
    RIGHT_MISMATCH: 'Quyền đỗ không phù hợp với phương tiện hoặc trạm.',
    EARLY_CONFLICT: 'Việc đến sớm xung đột với lượt đặt chỗ khác.',
    LATE_ARRIVAL: 'Đã quá thời hạn cho phép vào bãi.',
    RECEPTION_BLOCKED: 'Ô đỗ không đủ điều kiện tiếp nhận phương tiện.',
    NOT_PARKED: 'Phương tiện chưa được xác nhận đỗ tại vị trí phù hợp.',
    VISIT_ENDED: 'Lượt đỗ đã kết thúc hoặc đang rời bãi.',

    // Sạc điện
    INVALID_TARGET: 'Mức pin mục tiêu phải lớn hơn mức pin hiện tại.',
    NO_PORT: 'Không có cổng sạc tương thích khả dụng.',
    NO_POWER: 'Trạm không còn công suất sạc khả dụng.',
    POWER_CONFLICT: 'Công suất sạc bị xung đột hoặc vượt giới hạn.',
    PORT_CONFLICT: 'Cổng sạc đã được đặt trước.',
    PORT_IN_USE: 'Cổng sạc đang thuộc một phiên sạc khác.',
    PORT_UNAVAILABLE: 'Cổng sạc không đủ điều kiện sử dụng.',
    CHARGE_CONFLICT: 'Phương tiện có phiên sạc bị xung đột.',
    CHARGE_IN_USE: 'Phiên sạc đang sử dụng hoặc chờ xác nhận.',
    CHARGE_REQUEST_EXISTS: 'Phương tiện đã có yêu cầu sạc đang hoạt động.',
    INSUFFICIENT_TIME: 'Không đủ thời gian để đạt mức pin mục tiêu.',
    PERSONAL_VEHICLE_REQUIRED: 'Vui lòng chọn phương tiện cá nhân.',
    NOT_CONNECTED: 'Cần xác nhận kết nối hợp lệ với cổng sạc đang hoạt động.',
    CONNECTED: 'Cần xử lý phiên sạc và xác nhận ngắt kết nối.',
    INVALID_CONNECTION: 'Điều kiện kết nối đã thay đổi.',
    INVALID_START: 'Điều kiện bắt đầu sạc không còn hợp lệ.',
    INVALID_STOP: 'Yêu cầu dừng sạc không phù hợp với phiên hiện tại.',
    INVALID_UNPLUG: 'Không thể ngắt kết nối khi chưa xác nhận ngắt điện.',
    POWER_NOT_OFF: 'Cần xác nhận ngắt điện trước khi rút đầu nối.',
    OUTSIDE_SCHEDULE: 'Thao tác nằm ngoài khung thời gian được phép.',
    UNPLUG_PENDING: 'Vui lòng chờ xác nhận ngắt kết nối.',
    PREPARATION_REQUIRED: 'Cần chuẩn bị phương tiện tại ô đỗ có sạc.',

    // QR và thiết bị
    INVALID_QR: 'Mã QR không hợp lệ.',
    QR_UNAVAILABLE: 'Mã QR hiện chưa khả dụng.',
    DEVICE_SCOPE: 'Thông tin thiết bị không khớp với hồ sơ đăng ký.',
    POSITION_MISMATCH: 'Vị trí phương tiện không khớp với dữ liệu đã ghi nhận.',
    STALE_EVENT: 'Dữ liệu thiết bị không còn mới hoặc sai thứ tự.',
    SIMULATOR_DISABLED: 'Chế độ mô phỏng thiết bị chưa được bật.',
    UNKNOWN_EFFECT: 'Không nhận diện được tác động của lệnh thiết bị.',

    // Hỗ trợ và lập lịch
    NO_OFFER: 'Không có phương án tiếp nhận đang chờ phản hồi.',
    OFFER_EXPIRED: 'Phương án tiếp nhận đã hết hạn.',
    INVALID_RECORD: 'Hồ sơ không phù hợp với nghiệp vụ này.',
    STALE_PLAN: 'Dữ liệu đã thay đổi. Vui lòng tạo phương án mới.',
    UNMET_DEMAND: 'Phương án có nhu cầu chưa thể đáp ứng.',

    // Module D - Điều chuyển
    INVALID_ROUTE: 'Trạm xuất phát và trạm đích phải khác nhau.',
    INVALID_STAFF: 'Vui lòng chọn nhân viên điều phối hợp lệ.',
    STAFF_BUSY: 'Nhân viên điều phối đang có lệnh chưa hoàn thành.',
    TRANSFER_BLOCKED: 'Cần xử lý trạng thái phương tiện hoặc ô đỗ trước khi điều chuyển.',
    CLAIM_MISMATCH: 'Thông tin giữ tài nguyên không còn khớp với lệnh điều chuyển.',
    INVALID_HANDOVER: 'Phương tiện không đủ điều kiện bàn giao.',
    INVALID_RECOMMENDATION: 'Phương án đề xuất không hợp lệ.',

    // Module D - Bảo trì
    MAINTENANCE_LOCK: 'Tình trạng tài nguyên đang được quản lý bởi bộ phận bảo trì.',
    RESOURCE_BUSY: 'Tài nguyên phải ở trạng thái rảnh và chưa được giữ.',
    RESOURCE_UNAVAILABLE: 'Tài nguyên không đủ điều kiện hoạt động.',
    REPAIR_REQUIRED: 'Tài nguyên còn phiếu sửa chữa chưa hoàn thành.',
    ALREADY_ASSIGNED: 'Tài nguyên đã có yêu cầu sửa chữa.',
    INSPECTION_REQUIRED: 'Cần hoàn thành kiểm tra an toàn.',
    INVALID_ORIGIN: 'Yêu cầu hỗ trợ liên quan không hợp lệ.',
    STOP_PENDING: 'Cần hoàn tất việc dừng sạc trước khi tiếp tục.',
    UNKNOWN_TECHNICIAN: 'Không tìm thấy kỹ thuật viên.',
    UNKNOWN_VEHICLE: 'Không tìm thấy phương tiện.',

    // Hệ thống
    INTERNAL: 'Máy chủ gặp sự cố hoặc chưa xác nhận được kết quả yêu cầu.'
};

const apiMessageLabels = {
    // Đăng nhập
    'Incorrect username or password.':
        'Tên đăng nhập hoặc mật khẩu không chính xác.',

    'Enter a username and password.':
        'Vui lòng nhập tên đăng nhập và mật khẩu.',

    'Sign in to continue.':
        'Vui lòng đăng nhập để tiếp tục.',

    'Too many attempts. Try again in one minute.':
        'Bạn đã thử quá nhiều lần. Vui lòng thử lại sau một phút.',

    // Phân quyền
    'Student role required.':
        'Thao tác này chỉ dành cho sinh viên.',

    'Operator role required.':
        'Thao tác này chỉ dành cho nhân viên điều hành.',

    'Dispatcher action required.':
        'Thao tác này yêu cầu nhân viên điều phối.',

    'Technician action required.':
        'Thao tác này yêu cầu kỹ thuật viên.',

    'This record belongs to another user.':
        'Hồ sơ này thuộc về người dùng khác.',

    // Thuê xe
    'You already have a hold or an unfinished journey.':
        'Bạn đang có lượt giữ xe hoặc hành trình chưa kết thúc.',

    'Hold is not active.':
        'Lượt giữ xe không còn hoạt động.',

    'Only an active hold before handover can be cancelled.':
        'Chỉ có thể hủy lượt giữ xe đang hoạt động và chưa bàn giao.',

    // Đỗ xe
    'No ordinary reception capacity; request operator assistance.':
        'Không còn sức chứa tiếp nhận thông thường. Vui lòng yêu cầu nhân viên điều hành hỗ trợ.',

    'Parking must start now or within 24 hours.':
        'Thời gian đỗ xe phải bắt đầu từ hiện tại đến trong vòng 24 giờ tới.',

    'Personal parking must last 15 minutes to 12 hours.':
        'Thời gian đỗ phương tiện cá nhân phải từ 15 phút đến 12 giờ.',

    'End must follow arrival.':
        'Thời gian rời bãi phải sau thời gian đến.',

    // Sạc điện
    'Target SOC must exceed declared current SOC.':
        'Mức pin mục tiêu phải lớn hơn mức pin hiện tại đã khai báo.',

    'Target SOC must exceed current SOC.':
        'Mức pin mục tiêu phải lớn hơn mức pin hiện tại.',

    'No compatible charging port is available.':
        'Không có cổng sạc tương thích khả dụng.',

    'Parking spot has no compatible charging port.':
        'Ô đỗ không có cổng sạc tương thích.',

    'No charging power is available at this Hub.':
        'Trạm này không còn công suất sạc khả dụng.',

    'Requested SOC cannot be reached within parking window.':
        'Không thể đạt mức pin mục tiêu trong thời gian đỗ xe đã đăng ký.',

    'This vehicle already has an active charging request.':
        'Phương tiện này đã có yêu cầu sạc đang hoạt động.',

    'A rejection reason is required.':
        'Vui lòng nhập lý do từ chối.',

    'Only pending requests can be approved.':
        'Chỉ có thể phê duyệt yêu cầu đang chờ.',

    'Only pending requests can be rejected.':
        'Chỉ có thể từ chối yêu cầu đang chờ.',

    // QR và IoT
    'QR token is not recognized.':
        'Không nhận diện được mã QR.',

    'Charging QR is issued only after approval.':
        'Mã QR sạc điện chỉ được cấp sau khi phê duyệt.',

    'Device vehicle, Hub, bay or port does not match the reservation.':
        'Phương tiện, trạm, ô đỗ hoặc cổng sạc không khớp với thông tin đăng ký.',

    // Điều chuyển và bảo trì
    'Choose two different hubs.':
        'Vui lòng chọn hai trạm khác nhau.',

    'The dispatcher already has an active order.':
        'Nhân viên điều phối đang có lệnh điều chuyển chưa hoàn thành.',

    'A successful safety inspection is required.':
        'Cần hoàn thành kiểm tra an toàn đạt yêu cầu.',

    // Hệ thống
    'Request failed.':
        'Không thể thực hiện yêu cầu.',

    'Failed to fetch':
        'Không thể kết nối với máy chủ. Vui lòng kiểm tra kết nối.',

    'Resource state changed; generate a new plan.':
        'Trạng thái tài nguyên đã thay đổi. Vui lòng tạo phương án mới.',

    'Outcome uncertain. Retry the identical intent; do not submit a new request.':
        'Chưa xác định được kết quả. Hãy thử lại cùng yêu cầu, không tạo yêu cầu mới.',

    'Unable to load current state.':
        'Không thể tải trạng thái hiện tại.',

    'Unable to load rental QR.':
        'Không thể tải mã QR nhận xe.',

    'Unable to load charging QR.':
        'Không thể tải mã QR sạc điện.',

    'Unable to load parking QR.':
        'Không thể tải mã QR đỗ xe.',

    'Review the command and resource state in the device outbox.':
        'Vui lòng kiểm tra lệnh và trạng thái tài nguyên trong danh sách lệnh thiết bị.'
};
function apiMessageVi(message, code = '') {
    const raw = String(message ?? '');

    if (Object.hasOwn(apiMessageLabels, raw)) {
        return apiMessageLabels[raw];
    }

    if (Object.hasOwn(apiErrorLabels, code)) {
        return apiErrorLabels[code] +
            (raw ? ` (${raw})` : '');
    }

    return raw || 'Không thể thực hiện yêu cầu.';
}

function apiErrorText(error) {
    return apiMessageVi(
        error?.message,
        error?.code
    );
}
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
            heading: 'Thành công'
        },
        error: {
            icon: '!',
            heading: 'Thao tác thất bại'
        },
        warning: {
            icon: '!',
            heading: 'Cần xác nhận lại'
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
            aria-label="${retry ? 'Thử lại cùng yêu cầu' : 'Đóng thông báo'}"
        >
            ${retry ? 'Thử lại' : '×'}
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
    else showNotice(
        `Không thể làm mới dữ liệu: ${apiErrorText(error)}`,
        true
    );
    return false;
  }
}

async function command(action, payload, retry=false) {
  if (busy) return;
  const saved = pending();
  if (saved && !retry) {
    const message = 'Một yêu cầu trước đó chưa được xác nhận kết quả. ' + 'Vui lòng khôi phục yêu cầu trước khi thực hiện thao tác mới.';
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

        const reason = apiMessageVi(
            result.record?.reason ||
            'Review the command and resource state in the device outbox.'
        );

        showNotice(
            `${statusName(outcome)}. ${reason}`,
            true
        );

    } else if (result.status === 'PENDING_VERIFICATION') {

        showNotice(
            'Yêu cầu đã được ghi nhận. ' +
            'Đang chờ xác nhận bàn giao hoặc bằng chứng thiết bị.'
        );

    } else {

        showNotice(
            `${statusName(outcome || 'SAVED')}. ` +
            'Dữ liệu của bạn đã được cập nhật.'
        );

    }
  } catch (error) {
    if (error.status && error.status < 500) {
      localStorage.removeItem(pendingKey());
      if (error.status === 401) {state=null;renderLogin();}
      showNotice(apiErrorText(error), true);
    } else showNotice(
        'Mất phản hồi hoặc máy chủ chưa xác nhận được kết quả. ' +
        'Hãy thử lại cùng yêu cầu để khôi phục kết quả đã ghi nhận.',
        true,
        true
    );
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
  app.innerHTML = `<div class="login-shell"><section class="login-story"><div class="brand"><img class="brand-symbol" src="/icons/brand.svg" alt=""><div><strong>Smart E-Mobility</strong><small>MẠNG LƯỚI GIAO THÔNG ĐHQG-HCM</small></div></div><div><div class="eyebrow">Di chuyển xanh trong khuôn viên</div><h1>Hành trình mới.<br>Xanh hơn mỗi ngày.</h1><p>Tìm xe điện dùng chung, đặt chỗ đỗ và quản lý dịch vụ sạc trên một nền tảng kết nối.</p></div><div class="login-story-footer">Dịch vụ giao thông xanh · Bản trình diễn</div></section><main class="login-panel" id="main"><div class="login-card"><div class="eyebrow">Chào mừng bạn</div><h2>Đăng nhập hệ thống</h2><p class="muted">Sử dụng tài khoản demo để trải nghiệm các dịch vụ.</p><form id="login-form" class="form"><label>Tên đăng nhập<input name="username" autocomplete="username" required value="alice"></label><label>Mật khẩu<input name="password" type="password" autocomplete="current-password" required value="alice-demo"></label><button type="submit">Đăng nhập →</button><p class="login-error" id="login-error" role="alert"></p></form><div class="demo-note"><strong>Tài khoản dùng thử</strong><p><code>alice / alice-demo</code><br><code>bob / bob-demo</code><br><code>operator / operator-demo</code><br><code>dispatcher / dispatcher-demo</code><br><code>technician / technician-demo</code></p><p>Mật khẩu có thể được thay đổi thông qua cấu hình máy chủ. Tài khoản nhân viên được cấp quyền truy cập vào khu vực quản lý vận hành. Chế độ mô phỏng được bật khi khởi động máy chủ.</p></div></div></main></div>`;
  if (location.hostname.endsWith('.onrender.com')) {
    const input = app.querySelector('input[name="password"]');
    if (input) input.value = '';
    const notice = app.querySelector('.demo-note');
    if (notice) notice.innerHTML = '<strong>Bản trình diễn học thuật</strong><p>Đăng nhập bằng tài khoản tạm thời được quản trị viên dự án cung cấp. Các thao tác thiết bị được mô phỏng và dữ liệu có thể được đặt lại trên máy chủ miễn phí.</p>';
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
  app.innerHTML = `<div class="shell"><aside class="sidebar"><div class="brand"><img class="brand-symbol" src="/icons/brand.svg" alt=""><div class="brand-text"><strong>Smart<br>E-Mobility</strong><small>MẠNG LƯỚI ĐHQG-HCM</small></div></div><div class="nav-label">KHÔNG GIAN LÀM VIỆC</div><nav class="nav" aria-label="Điều hướng chính">${availableTabs.map(([id,icon,label])=>`<button data-tab="${id}" class="${tab===id?'active':''}" ${tab===id?'aria-current="page"':''} title="${label}" aria-label="${label}"><img class="icon" src="/icons/${id}.svg" alt=""><span class="nav-text">${label}</span></button>`).join('')}</nav><div class="sidebar-foot">
    <strong>Kết nối khuôn viên.<br>Hành trình xanh hơn.</strong>

    <p class="spaced">
        Thuê xe và hành trình<br>
        Đỗ xe và sức chứa<br>
        Sạc điện và lịch sạc<br>
        Điều phối đội xe
    </p>

    <p class="spaced">
        Bản trình diễn · ${esc(roleName(state.actor.role))}
    </p>
</div></aside><div class="main-column"><header class="topbar"><div class="breadcrumb">
    ĐHQG-HCM / Dịch vụ di chuyển /
    <strong>${esc(tabs.find(row=>row[0]===tab)[2])}</strong>
</div><div class="account"><span class="avatar">${esc(state.actor.id[0].toUpperCase())}</span><div><strong>${esc(title(state.actor.id))}</strong><div class="small-text muted">${esc(roleName(state.actor.role))}</div></div><button class="secondary small" id="logout">Đăng xuất</button></div></header><main class="content" id="main"><div class="mode-banner">
${pending() ? `
    <div class="record-note spaced">
        <strong>Yêu cầu đang chờ xác nhận</strong>
        <p>
            Một yêu cầu trước đó chưa được xác nhận kết quả.
        </p>
        <button
            type="button"
            class="secondary small"
            id="recover-pending"
        >
            Khôi phục yêu cầu
        </button>
    </div>
` : ''}
<strong>
    ${state.simulator
        ? '◇ Chế độ mô phỏng đang bật'
        : '◇ Chế độ mô phỏng đang tắt'}
</strong><span>
    ${state.simulator
        ? 'Tất cả bằng chứng thiết bị đều được mô phỏng. Nhân viên điều hành phải xác nhận từng kết quả mô phỏng.'
        : 'Các yêu cầu bàn giao và sạc điện sẽ tiếp tục chờ cho đến khi nhận được bằng chứng xác nhận.'}
</span></div>${views[tab]()}</main></div></div>`;
  const saved = pending();

  if (!saved) {
      lastNotifiedPending = null;
  } else {
      const pendingId =
          `${state.actor.id}:${saved.intent_id}`;

      if (lastNotifiedPending !== pendingId) {
          lastNotifiedPending = pendingId;

          showNotice(
              'Có một yêu cầu chưa xác định được kết quả. Vui lòng khôi phục yêu cầu đã lưu.',
              true,
              true
          );
      }
  }
}

function heading(kicker, name, description, extra='') {
  return `<div class="page-title"><div><div class="eyebrow">${esc(kicker)}</div><h1>${esc(name)}</h1><p>${esc(description)}</p></div><div class="toolbar"><button class="secondary small" id="refresh">↻ Làm mới</button>${extra}</div></div>`;
}


function overview() {
    const hubs = list('hubs');

    const vehicles = list('vehicles').filter(
        v => v.kind === 'shared' &&
            (!selectedHub || v.hub_id === selectedHub)
    );

    return heading(
        'Khám phá mạng lưới',
        'Bạn muốn đi đâu?',
    ) +

    `<section class="stats" aria-label="Tổng quan mạng lưới">

        <div class="stat">
            <div class="label">Trạm di chuyển</div>
            <div class="number">${hubs.length}</div>
            <div class="hint">
                Metro · Trường đại học · Ký túc xá
            </div>
        </div>

        <div class="stat">
            <div class="label">Xe dùng chung khả dụng</div>
            <div class="number">
                ${list('vehicles').filter(
                    v => v.kind === 'shared' && v.available
                ).length}
            </div>
            <div class="hint">
                Dữ liệu còn mới, đủ điều kiện và chưa được giữ
            </div>
        </div>

        <div class="stat">
            <div class="label">Chỗ đỗ khả dụng</div>
            <div class="number">
                ${hubs.reduce(
                    (n, h) => n + (h.available || 0), 0
                )}
            </div>
            <div class="hint">
                Theo thời gian và chính sách tiếp nhận
            </div>
        </div>

        <div class="stat">
            <div class="label">Dịch vụ đang sử dụng</div>
            <div class="number">${state.active_services}</div>
            <div class="hint">
                Quản lý trong không gian làm việc
            </div>
        </div>

    </section>` +

    `<div class="section-heading">
        <h2>Tìm trạm phù hợp</h2>

        <span class="state-age">
            Cập nhật ${esc(date(state.now))}
            · Phiên bản ${esc(state.revision)}
        </span>
    </div>

    <div class="grid">

        ${hubs.map((hub, i) => `

            <article class="card hub-card">

                <div class="hub-art">
                    <span>
                        0${i + 1} / ${esc(hubName(hub.id))}
                    </span>
                </div>

                <div class="card-body">

                    <div class="card-heading">
                        <div>
                            <h3>${esc(hubName(hub.id))}</h3>

                            <p class="muted small-text">
                                ${esc(hub.id)} ·
                                Công suất sạc
                                ${esc(hub.power_kw)} kW
                            </p>
                        </div>

                        ${chip(hub.level || 'OPEN')}
                    </div>

                    <div class="capacity">

                        <div class="capacity-line">
                            <span>Mức sử dụng chỗ đỗ</span>

                            <strong>
                                ${
                                    (hub.occupied || 0) +
                                    (hub.unknown || 0) +
                                    (hub.held || 0)
                                } / ${hub.capacity}
                            </strong>
                        </div>

                        <progress
                            class="meter ${hub.available < 3 ? 'warn' : ''}"
                            max="${hub.capacity || 1}"
                            value="${
                                (hub.occupied || 0) +
                                (hub.unknown || 0) +
                                (hub.held || 0)
                            }"
                            aria-label="Mức cam kết sử dụng chỗ đỗ"
                        ></progress>

                        <div class="facts">
                            <span>
                                ${hub.occupied || 0} đang sử dụng
                            </span>

                            <span>
                                ${hub.held || 0} đã giữ
                            </span>

                            <span>
                                ${hub.unknown || 0} chưa xác định
                            </span>
                        </div>

                    </div>

                    <div class="card-footer">

                        <span class="small-text muted">
                            ${
                                list('vehicles').filter(
                                    v => v.kind === 'shared' &&
                                        v.hub_id === hub.id &&
                                        v.available
                                ).length
                            } xe khả dụng
                        </span>

                        <button
                            class="link"
                            data-hub="${esc(hub.id)}"
                        >
                            Xem phương tiện →
                        </button>

                    </div>

                </div>

            </article>

        `).join('')}

    </div>` +

    `<div class="section-heading">

        <h2>Phương tiện dùng chung</h2>

        <label
            class="visually-hidden"
            for="hub-filter"
        >
            Lọc theo trạm
        </label>

        <select id="hub-filter" class="inline-input">

            ${option('', 'Tất cả trạm', !selectedHub)}

            ${hubs.map(h =>
                option(
                    h.id,
                    hubName(h.id),
                    h.id === selectedHub
                )
            ).join('')}

        </select>

    </div>

    ${vehicles.length ? `

        <div class="table-wrap">

            <table>

                <thead>
                    <tr>
                        <th>Phương tiện</th>
                        <th>Vị trí</th>
                        <th>Pin</th>
                        <th>Dữ liệu quan sát</th>
                        <th>Khả dụng</th>
                        <th>Thao tác</th>
                    </tr>
                </thead>

                <tbody>

                    ${vehicles.map(v => `

                        <tr>

                            <td class="vehicle-name">
                                ${esc(v.label || v.id)}
                            </td>

                            <td>

                                ${esc(hubName(v.hub_id))}

                                <br>

                                <span class="muted small-text">
                                    ${v.spot_id
                                        ? `Ô đỗ ${esc(v.spot_id)}`
                                        : 'Chưa được gán ô đỗ'}
                                </span>

                            </td>

                            <td>
                                <span class="battery">
                                    ▰ ${esc(v.soc)}%
                                </span>
                            </td>

                            <td>
                                ${chip(
                                    v.freshness ||
                                    (
                                        now() - v.observed_at > 90
                                            ? 'STALE'
                                            : 'FRESH'
                                    )
                                )}
                            </td>

                            <td>
                                ${chip(
                                    v.available
                                        ? 'AVAILABLE'
                                        : v.health !== 'OPERABLE'
                                            ? v.health
                                            : 'UNAVAILABLE'
                                )}
                            </td>

                            <td>
                                ${
                                    state.actor.role === 'student' &&
                                    v.available

                                    ? actionButton(
                                        'Giữ xe · 10 phút',
                                        'reserve_vehicle',
                                        {vehicle_id: v.id},
                                        'small'
                                    )

                                    : '—'
                                }
                            </td>

                        </tr>

                    `).join('')}

                </tbody>

            </table>

        </div>

    ` : empty(
        'Không có phương tiện dùng chung tại trạm này',
        'Vui lòng chọn trạm khác hoặc kiểm tra lại sau khi có phương tiện được tiếp nhận.'
    )}

    <p class="muted small-text spaced">

        Thời gian giữ xe là 10 phút.
        Chỗ đỗ tại trạm trả xe được đăng ký riêng.
        Dữ liệu quan sát đã cũ không được sử dụng
        để cấp phát tài nguyên mới.

    </p>`;
}



function journeys() {
    const holds = list('holds').slice().reverse();
    const trips = list('trips').slice().reverse();

    const openTrips = trips.filter(
        t => t.status !== 'CLOSED'
    );

    return heading(
        'Thuê xe và hành trình',
        'Quản lý hành trình của bạn',
        'Xuất trình mã QR tại trạm. Trạng thái nhận và trả xe sẽ được cập nhật sau khi có xác nhận.'
    ) +

    `<div class="split">

        <section>

            <div class="section-heading">
                <h2>Danh sách giữ xe</h2>

                <button class="link" data-tab="overview">
                    Tìm phương tiện →
                </button>
            </div>

            <div class="records">

                ${holds.length ? holds.map(h => `

                    <article class="record">

                        <div class="record-main">

                            <div>
                                <div class="record-title">

                                    <h3>
                                        ${esc(vehicleName(h.vehicle_id))}
                                    </h3>

                                    <span class="record-id">
                                        ${esc(h.id)}
                                    </span>

                                </div>

                                <div class="record-meta">
                                    <span>
                                        Giữ xe đến ${date(h.expires_at)}
                                    </span>
                                </div>
                            </div>

                            ${chip(h.status)}

                        </div>

                        ${rentalQrButton(h)}

                        ${h.status === 'ACTIVE' ? `

                            <div class="record-actions">

                                ${actionButton(
                                    'Hủy giữ xe',
                                    'cancel_hold',
                                    {hold_id: h.id},
                                    'danger small'
                                )}

                            </div>

                        ` : ''}

                        ${/PENDING/.test(h.status) ? `

                            <div class="record-note">
                                Việc bàn giao đang chờ bằng chứng xác nhận.
                                Hết hạn hoặc yêu cầu hủy không tự động
                                giải phóng phương tiện này.
                            </div>

                        ` : ''}

                    </article>

                `).join('') : empty(
                    'Chưa có lượt giữ xe',
                    'Hãy chọn và giữ một phương tiện dùng chung đủ điều kiện tại trang Khám phá trạm.'
                )}

            </div>

            <div class="section-heading">
                <h2>Danh sách hành trình</h2>
            </div>

            <div class="records">

                ${trips.length ? trips.map(t => `

                    <article class="record">

                        <div class="record-main">

                            <div>

                                <div class="record-title">

                                    <h3>
                                        ${esc(vehicleName(t.vehicle_id))}
                                    </h3>

                                    <span class="record-id">
                                        ${esc(t.id)}
                                    </span>

                                </div>

                                <div class="record-meta">

                                    <span>
                                        Bắt đầu ${date(t.started_at)}
                                    </span>

                                    <span>
                                        ${t.ended_at
                                            ? 'Đã trả xe ' + date(t.ended_at)
                                            : 'Trách nhiệm bàn giao xe chưa kết thúc'}
                                    </span>

                                </div>

                            </div>

                            ${chip(t.status)}

                        </div>

                        ${t.status === 'ASSISTANCE_PENDING' ? `

                            <div class="record-note">
                                Việc tiếp nhận xe cần sự hỗ trợ của
                                nhân viên điều hành. Hành trình vẫn đang
                                mở; hãy xem mục Hỗ trợ để biết phương án
                                tiếp nhận được đề xuất.
                            </div>

                        ` : ''}

                    </article>

                `).join('') : empty(
                    'Hành trình tiếp theo của bạn bắt đầu tại đây',
                    'Hành trình xuất hiện sau khi bằng chứng nhận xe được chấp nhận.'
                )}

            </div>

        </section>

        <aside>

            <div class="card">

                <div class="card-body">

                    <div class="eyebrow">
                        Lập kế hoạch trả xe
                    </div>

                    <h2>Chọn trạm trả xe</h2>

                    <p class="muted small-text spaced">
                        Lưu trạm dự kiến trước khi trả xe.
                        Thao tác này không xác nhận đã trả xe
                        hoặc giữ ô đỗ.
                    </p>

                    <form
                        class="form spaced"
                        data-command="select_return_hub"
                    >

                        <label>
                            Hành trình đang mở

                            <select name="trip_id" required>

                                ${option('', 'Chọn hành trình')}

                                ${openTrips.map(t =>
                                    option(
                                        t.id,
                                        `${t.id} · ${t.vehicle_id}`
                                    )
                                ).join('')}

                            </select>
                        </label>

                        <label>
                            Trạm trả xe

                            <select name="hub_id" required>
                                ${hubOptions()}
                            </select>
                        </label>

                        <label>
                            Quyền đỗ xe hiện có (không bắt buộc)

                            <select name="right_id">

                                ${option(
                                    '',
                                    'Không có quyền đỗ xe'
                                )}

                                ${list('rights')
                                    .filter(r => [
                                        'CONFIRMED',
                                        'HANDOVER_PENDING'
                                    ].includes(r.status))
                                    .map(r =>
                                        option(
                                            r.id,
                                            `${r.id} · ${hubName(r.hub_id)} · ${r.vehicle_id}`
                                        )
                                    ).join('')}

                            </select>
                        </label>

                        <button type="submit">
                            Lưu trạm trả xe
                        </button>

                    </form>

                </div>

            </div>

            <div class="card spaced">

                <div class="card-body">

                    <h3>
                        Bạn cần chỗ đỗ tại trạm trả xe?
                    </h3>

                    <p class="muted small-text spaced">
                        Lượt giữ xe không bao gồm ô đỗ tại trạm
                        trả xe. Bạn có thể đăng ký riêng quyền đỗ
                        cho phương tiện dùng chung trước khi đến.
                    </p>

                    <button
                        class="link spaced"
                        data-tab="parking"
                    >
                        Đặt chỗ đỗ xe →
                    </button>

                </div>

            </div>

        </aside>

    </div>`;
}


const hubOptions = () =>
    list('hubs').map(h =>
        option(
            h.id,
            hubName(h.id),
            selectedHub === h.id
        )
    ).join('');
const myVehicles = () => list('vehicles').filter(v=>v.owner_id===state.actor.id || (v.kind==='shared' && [...list('holds'),...list('trips')].some(r=>r.owner_id===state.actor.id&&r.vehicle_id===v.id&&!['CANCELLED','EXPIRED','CONSUMED','CLOSED'].includes(r.status))));


function parking() {
    const rights = list('rights').slice().reverse();
    const visits = list('visits').slice().reverse();

    return heading(
        'Đỗ xe và sức chứa',
        'Đặt chỗ đỗ xe khi bạn cần',
        'Đặt trước tối đa 24 giờ. Thời gian đỗ xe cá nhân từ 15 phút đến 12 giờ, với khoảng cách 15 phút giữa hai lượt đặt.'
    ) +

    `<div class="split">

        <section>

            <div class="section-heading">
                <h2>Danh sách quyền đỗ xe</h2>
            </div>

            <div class="records">

                ${rights.length ? rights.map(r => `

                    <article class="record">

                        <div class="record-main">

                            <div>

                                <div class="record-title">

                                    <h3>${esc(hubName(r.hub_id))}</h3>

                                    <span class="record-id">
                                        ${esc(r.id)}
                                    </span>

                                </div>

                                <div class="record-meta">

                                    <span>
                                        ${esc(vehicleName(r.vehicle_id))}
                                    </span>

                                    <span>
                                        Ô đỗ ${esc(r.spot_id)}
                                    </span>

                                </div>

                                <p class="muted small-text">
                                    ${date(r.start)}
                                    →
                                    ${r.end
                                        ? date(r.end)
                                        : 'Đến khi xác nhận rời bãi'}
                                </p>

                            </div>

                            ${chip(r.status)}

                        </div>

                        <div class="record-actions">
                            ${parkingQrButton(r)}
                        </div>

                        ${r.status === 'CONFIRMED' ? `

                            <div class="record-actions">

                                ${actionButton(
                                    'Hủy quyền đỗ chưa sử dụng',
                                    'cancel_parking',
                                    {right_id: r.id},
                                    'danger small'
                                )}

                            </div>

                        ` : ''}

                        ${r.status === 'HANDOVER_PENDING' ? `

                            <div class="record-note">
                                Đang chờ bằng chứng xác nhận vào bãi.
                                Quyền sử dụng ô đỗ vẫn được bảo vệ.
                            </div>

                        ` : ''}

                    </article>

                `).join('') : empty(
                    'Chưa có quyền đỗ xe',
                    'Hãy đặt một ô đỗ hoặc đăng ký đồng thời dịch vụ đỗ xe và sạc điện.'
                )}

            </div>

            <div class="section-heading">
                <h2>Các lượt đỗ xe thực tế</h2>
            </div>

            <div class="records">

                ${visits.length ? visits.map(v => `

                    <article class="record">

                        <div class="record-main">

                            <div>

                                <h3>
                                    ${esc(vehicleName(v.vehicle_id))}
                                </h3>

                                <div class="record-meta">

                                    <span>
                                        Ô đỗ ${esc(v.spot_id)}
                                    </span>

                                    <span class="record-id">
                                        ${esc(v.id)}
                                    </span>

                                </div>

                            </div>

                            ${chip(v.status)}

                        </div>

                        <div class="record-note">
                            Hết thời gian đặt chỗ không tự động
                            giải phóng ô đỗ đang có phương tiện.
                            Việc rời bãi cần bằng chứng xác nhận
                            và thiết bị sạc phải được ngắt kết nối.
                        </div>

                    </article>

                `).join('') : empty(
                    'Chưa có lượt đỗ xe',
                    'Lượt đỗ được tạo sau khi bằng chứng vào bãi được chấp nhận.'
                )}

            </div>

        </section>

        <aside>

            <div class="card">

                <div class="card-body">

                    <div class="eyebrow">
                        Đặt trước chỗ đỗ
                    </div>

                    <h2>Đăng ký dịch vụ đỗ xe</h2>

                    <form
                        class="form spaced"
                        data-command="reserve_parking"
                    >

                        <label>
                            Phương tiện

                            <select name="vehicle_id" required>

                                ${option('', 'Chọn phương tiện')}

                                ${myVehicles().map(v =>
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
                            Thời gian đến

                            <input
                                name="start"
                                type="datetime-local"
                                required
                                value="${inputDate(now() + 120)}"
                            >
                        </label>

                        <label>
                            Thời gian rời bãi dự kiến

                            <input
                                name="end"
                                type="datetime-local"
                                required
                                value="${inputDate(now() + 3720)}"
                            >

                            <span class="form-help">
                                Phương tiện dùng chung chiếm ô đỗ
                                tại trạm trả xe cho đến khi việc
                                rời bãi được xác nhận.
                            </span>
                        </label>

                        <label class="check-label">

                            <input
                                type="checkbox"
                                name="charging"
                            >

                            Đăng ký kèm sạc điện
                            (phương tiện cá nhân)

                        </label>

                        <label>
                            Mức pin mục tiêu (SOC %)

                            <input
                                name="target_soc"
                                type="number"
                                min="1"
                                max="100"
                                value="80"
                            >
                        </label>

                        <label>
                            Liên kết lượt giữ xe
                            (không bắt buộc)

                            <select name="hold_id">

                                ${option(
                                    '',
                                    'Quyền đỗ xe độc lập'
                                )}

                                ${list('holds')
                                    .filter(h => h.status === 'ACTIVE')
                                    .map(h =>
                                        option(
                                            h.id,
                                            `${h.id} · ${h.vehicle_id}`
                                        )
                                    ).join('')}

                            </select>
                        </label>

                        <button type="submit">
                            Xác nhận đặt chỗ
                        </button>

                        <p class="form-help">
                            Gói đỗ xe và sạc điện cấp phát đồng thời
                            cả hai tài nguyên. Nếu không đủ điều kiện,
                            hệ thống không tự chuyển sang chỉ đỗ xe.
                        </p>

                    </form>

                </div>

            </div>

            <div class="card spaced">

                <div class="card-body">

                    <h3>Đăng ký phương tiện cá nhân</h3>

                    ${vehicleForm()}

                </div>

            </div>

        </aside>

    </div>`;
}



function vehicleForm() {
    return `

        <form
            class="form spaced"
            data-command="register_vehicle"
        >

            <label>
                Tên phương tiện

                <input
                    name="label"
                    maxlength="80"
                    required
                    placeholder="Xe đạp điện của tôi"
                >
            </label>

            <div class="form-row">

                <label>
                    Dung lượng pin (kWh)

                    <input
                        name="battery_kwh"
                        type="number"
                        min="0.1"
                        max="100"
                        step="0.1"
                        value="2"
                        required
                    >
                </label>

                <label>
                    Mức pin hiện tại (SOC %)

                    <input
                        name="soc"
                        type="number"
                        min="0"
                        max="99"
                        value="30"
                        required
                    >
                </label>

            </div>

            <label>
                Loại đầu nối sạc

                <select name="connector">

                    ${option('TYPE2', 'Type 2')}
                    ${option('SCHUKO', 'Schuko')}

                </select>
            </label>

            <button
                class="secondary"
                type="submit"
            >
                Đăng ký phương tiện
            </button>

            <p class="form-help">
                Thông tin pin do người dùng khai báo
                được sử dụng để ước tính, không phải
                kết quả đo thực tế từ thiết bị.
            </p>

        </form>`;
}


function charging() {
    const sessions = list('sessions').slice().reverse();

    const eligibleRights = compatibleChargingRights();

    return heading(
        'Dịch vụ sạc điện',
        'Sạc điện an tâm',
        'Đăng ký sạc trực tiếp, nhận thông tin cấp phát và mã QR sau khi nhân viên điều hành xác nhận.'
    ) +

    chargingRequestForm() +

    chargingRequestCards() +

    `<section class="spaced">

        <div class="card">

            <div class="card-body">

                <div class="eyebrow">
                    Sử dụng quyền đỗ xe hiện có
                </div>

                <h2>Đăng ký bổ sung dịch vụ sạc</h2>

                <form
                    class="form spaced"
                    data-command="register_charge"
                >

                    <label>
                        Quyền đỗ xe

                        <select name="right_id" required>

                            ${option(
                                '',
                                'Chọn quyền đỗ xe tương thích'
                            )}

                            ${eligibleRights.map(r =>
                                option(
                                    r.id,
                                    `${r.id} · ${r.vehicle_id} · ${r.spot_id}`
                                )
                            ).join('')}

                        </select>
                    </label>

                    <label>
                        Mức pin mục tiêu (SOC %)

                        <input
                            type="number"
                            name="target_soc"
                            min="1"
                            max="100"
                            value="80"
                            required
                        >
                    </label>

                    <button type="submit">
                        Đăng ký sạc điện
                    </button>

                    <p class="form-help">
                        Quyền đỗ xe phải bao phủ toàn bộ khung giờ sạc
                        và thuộc ô đỗ có cổng sạc tương thích.
                        Quyền đỗ được tạo độc lập vẫn được giữ nguyên
                        khi hủy dịch vụ sạc.
                    </p>

                </form>

            </div>

        </div>

        <div class="card spaced">

            <div class="card-body">

                <h3>Quy trình thực hiện một phiên sạc</h3>

                <ol class="review-list">

                    <li>
                        Đăng ký dịch vụ đỗ xe và sạc điện.
                    </li>

                    <li>
                        Xuất trình mã QR tại ô đỗ được cấp
                        và chờ xác minh.
                    </li>

                    <li>
                        Kết nối phương tiện với cổng sạc
                        và chờ xác nhận kết nối.
                    </li>

                    <li>
                        Quá trình sạc bắt đầu sau khi kết nối
                        được xác minh và thiết bị xác nhận cấp điện.
                    </li>

                    <li>
                        Dừng sạc nếu cần và chờ xác nhận ngắt điện.
                    </li>

                    <li>
                        Ngắt kết nối, nhận phương tiện và rời bãi.
                        Trạng thái được cập nhật sau khi xác minh.
                    </li>

                </ol>

            </div>

        </div>

    </section>` +

    `<div>

        <section>

            <div class="section-heading">

                <h2>Danh sách phiên sạc</h2>

                <button
                    class="link"
                    data-tab="parking"
                >
                    Đặt chỗ đỗ và sạc điện →
                </button>

            </div>

            <div class="records">

                ${sessions.length ? sessions.map(s => {

                    const port = find('ports', s.port_id);

                    return `
                        <article class="record">

                            <div class="record-main">

                                <div>

                                    <div class="record-title">

                                        <h3>
                                            ${esc(vehicleName(s.vehicle_id))}
                                        </h3>

                                        <span class="record-id">
                                            ${esc(s.id)}
                                        </span>

                                    </div>

                                    <div class="record-meta">

                                        <span>
                                            Cổng sạc ${esc(s.port_id)}
                                        </span>

                                        <span>
                                            Mục tiêu
                                            ${esc(s.target_soc)}%
                                        </span>

                                        <span>
                                            ${esc(s.kw || '—')} kW
                                        </span>

                                    </div>

                                    <p class="muted small-text">

                                        Khung giờ đăng ký:
                                        ${date(s.start)}
                                        →
                                        ${date(s.end)}

                                    </p>

                                    <p class="muted small-text">

                                        Lịch sạc được cấp:
                                        ${date(s.scheduled_start)}
                                        →
                                        ${date(s.scheduled_end)}

                                    </p>

                                </div>

                                ${chip(s.status)}

                            </div>

                            <div class="record-note">

                                Trạng thái cổng sạc:

                                ${esc(statusName(
                                    port?.plug || 'UNKNOWN'
                                ))}

                                · Nguồn điện:

                                ${esc(statusName(
                                    port?.power || 'UNKNOWN'
                                ))}

                                · ${esc(statusName(
                                    port?.health || 'UNKNOWN'
                                ))}

                            </div>

                            <div class="record-actions">

                                ${s.status === 'BOOKED'

                                    ? actionButton(
                                        'Hủy phiên sạc chưa sử dụng',
                                        'cancel_charge',
                                        {session_id: s.id},
                                        'danger small'
                                    )

                                    : ''}

                                ${[
                                    'CHARGING',
                                    'START_PENDING',
                                    'STOP_PENDING'
                                ].includes(s.status)

                                    ? actionButton(
                                        'Dừng sạc',
                                        'stop_charge',
                                        {session_id: s.id},
                                        'small'
                                    )

                                    : ''}

                            </div>

                            ${s.status === 'COMPLETED' ? `

                                <p class="muted small-text spaced">
                                    Phiên sạc đã hoàn thành.
                                    Cổng sạc vẫn được ghi nhận là
                                    đang sử dụng cho đến khi việc ngắt
                                    kết nối được xác nhận.
                                    Ô đỗ chỉ được giải phóng khi
                                    phương tiện rời bãi.
                                </p>

                            ` : ''}

                        </article>`;
                }).join('') : empty(
                    'Chưa có phiên sạc điện',
                    'Đăng ký gói đỗ xe và sạc điện hoặc bổ sung dịch vụ sạc vào quyền đỗ xe tương thích.'
                )}

            </div>

            <div class="section-heading">
                <h2>Cổng sạc và trạng thái thiết bị</h2>
            </div>

            <div class="table-wrap">

                <table>

                    <thead>
                        <tr>
                            <th>Cổng sạc / Ô đỗ</th>
                            <th>Kết nối</th>
                            <th>Nguồn điện</th>
                            <th>Tình trạng kỹ thuật</th>
                            <th>Dữ liệu quan sát</th>
                        </tr>
                    </thead>

                    <tbody>

                        ${list('ports').map(p => `

                            <tr>

                                <td>
                                    ${esc(p.id)}
                                    /
                                    ${esc(p.spot_id)}
                                </td>

                                <td>
                                    ${chip(p.plug)}
                                </td>

                                <td>
                                    ${chip(p.power)}
                                </td>

                                <td>
                                    ${chip(p.health)}
                                </td>

                                <td>

                                    ${chip(
                                        p.freshness ||
                                        (
                                            now() - p.observed_at > 90
                                                ? 'STALE'
                                                : 'FRESH'
                                        )
                                    )}

                                </td>

                            </tr>

                        `).join('')}

                    </tbody>

                </table>

            </div>

        </section>

    </div>`;
}


function receptionOffer(incident) {
    const right = find(
        'rights',
        incident.offered_right_id
    );

    if (!right) return '';

    return `
        <div class="record-note">

            <strong>
                Phương án tiếp nhận ·
                ${esc(hubName(right.hub_id))}
            </strong>

            <p>
                Ô đỗ ${esc(right.spot_id)}
                dành cho
                ${esc(vehicleName(right.vehicle_id))}.

                Vui lòng phản hồi trước
                ${date(incident.offer_expires_at)}.
            </p>

        </div>`;
}


function support() {
    const records = [
        ...list('holds'),
        ...list('trips'),
        ...list('rights'),
        ...list('visits'),
        ...list('sessions')
    ];

    return heading(
        'Hỗ trợ hành trình',
        'Luôn đồng hành cùng bạn',
        'Ghi nhận các sự cố hoặc khó khăn khi tiếp nhận phương tiện. Phương án của nhân viên điều hành cần được bạn phản hồi và không tự động kết thúc hành trình.'
    ) +

    `<div class="split">

        <section>

            <div class="section-heading">
                <h2>Danh sách yêu cầu hỗ trợ</h2>
            </div>

            <div class="records">

                ${list('incidents').length
                    ? list('incidents')
                        .slice()
                        .reverse()
                        .map(i => `

                    <article class="record">

                        <div class="record-main">

                            <div>

                                <h3>
                                    ${esc(
                                        i.message ||
                                        'Hỗ trợ tiếp nhận phương tiện'
                                    )}
                                </h3>

                                <div class="record-meta">

                                    <span class="record-id">
                                        ${esc(i.id)}
                                    </span>

                                    <span>
                                        Hồ sơ liên quan
                                        ${esc(i.record_id)}
                                    </span>

                                </div>

                            </div>

                            ${chip(i.status)}

                        </div>

                        ${i.response ? `

                            <div class="record-note">
                                ${typeof i.response === 'string'
                                    ? esc(i.response)
                                    : detailValue(i.response)}
                            </div>

                        ` : ''}

                        ${i.status === 'OFFERED'
                            ? receptionOffer(i)
                            : ''}

                        ${state.actor.role === 'student' &&
                            i.status === 'OFFERED' ? `

                            <div class="record-actions">

                                ${actionButton(
                                    'Chấp nhận phương án',
                                    'accept_capacity',
                                    {
                                        incident_id: i.id,
                                        accept: true
                                    },
                                    'small'
                                )}

                                ${actionButton(
                                    'Từ chối phương án',
                                    'accept_capacity',
                                    {
                                        incident_id: i.id,
                                        accept: false
                                    },
                                    'danger small'
                                )}

                            </div>

                        ` : ''}

                    </article>

                `).join('') : empty(
                    'Chưa có yêu cầu hỗ trợ',
                    'Bạn có thể báo cáo sự cố liên quan đến một trong các dịch vụ của mình.'
                )}

            </div>

        </section>

        <aside>

            <div class="card">

                <div class="card-body">

                    <h2>Gửi yêu cầu hỗ trợ</h2>

                    <form
                        class="form spaced"
                        data-command="support"
                    >

                        <label>
                            Dịch vụ liên quan

                            <select name="record_id" required>

                                ${option(
                                    '',
                                    'Chọn dịch vụ cần hỗ trợ'
                                )}

                                ${records.map(r =>
                                    option(
                                        r.id,
                                        `${r.id} · ${
                                            r.vehicle_id ||
                                            statusName(r.status)
                                        }`
                                    )
                                ).join('')}

                            </select>
                        </label>

                        <label>
                            Bạn đang gặp vấn đề gì?

                            <textarea
                                name="message"
                                required
                                minlength="5"
                                maxlength="1000"
                                placeholder="Mô tả sự cố và vị trí hiện tại của bạn."
                            ></textarea>

                        </label>

                        <button type="submit">
                            Gửi yêu cầu hỗ trợ
                        </button>

                        <p class="form-help">
                            Nhân viên điều hành có thể sử dụng
                            yêu cầu này để tạo phiếu bảo trì
                            cho tài nguyên gặp sự cố.
                        </p>

                    </form>

                </div>

            </div>

        </aside>

    </div>`;
}



function operations() {
    const commands = list('commands');

    const capacityCases = list('incidents').filter(i => {
        if (![
            'OPEN',
            'WAITING_FOR_D',
            'DECLINED'
        ].includes(i.status)) return false;

        const trip = find('trips', i.record_id);
        const right = find('rights', i.record_id);

        return (
            trip && trip.status !== 'CLOSED'
        ) || right?.status === 'CONFIRMED';
    });

    const fleetVehicles = list('vehicles').filter(v =>
        v.kind === 'shared' &&
        !v.transfer_order_id &&
        v.health === 'OPERABLE' &&
        v.soc < 100 &&
        list('ports').some(p =>
            p.spot_id === v.spot_id &&
            p.connector === v.connector
        )
    );

    return heading(
        'Không gian điều hành',
        'Điều hành mạng lưới di chuyển',
        'Xem xét phương án tiếp nhận và lịch sạc. Việc xác nhận kế hoạch không đồng nghĩa với xác nhận phương tiện đã di chuyển trên thực tế.'
    ) +

    chargingRequestCards(true) +

    `<div class="grid two">

        <div class="card">

            <div class="card-body">

                <div class="eyebrow">
                    B05 · Khôi phục sức chứa
                </div>

                <h2>Đề xuất phương án tiếp nhận</h2>

                <form
                    class="form spaced"
                    data-command="capacity_plan"
                >

                    <label>
                        Yêu cầu hỗ trợ

                        <select name="incident_id" required>

                            ${option(
                                '',
                                'Chọn yêu cầu chưa giải quyết'
                            )}

                            ${capacityCases.map(i =>
                                option(
                                    i.id,
                                    `${i.id} · ${i.message || i.record_id}`
                                )
                            ).join('')}

                        </select>
                    </label>

                    <label>
                        Trạm tiếp nhận thay thế

                        <select name="hub_id" required>
                            ${hubOptions()}
                        </select>
                    </label>

                    <label>
                        Lý do sử dụng sức chứa dự phòng

                        <input
                            name="reason"
                            required
                            minlength="5"
                            maxlength="500"
                            placeholder="Đảm bảo khả năng tiếp nhận cho hành trình bị gián đoạn"
                        >
                    </label>

                    <button type="submit">
                        Đề xuất tiếp nhận
                    </button>

                    <p class="form-help">
                        Sức chứa được kiểm tra lại và các cam kết
                        hiện có vẫn được bảo vệ.
                        Chủ sở hữu phải chấp nhận phương án
                        trước khi yêu cầu bàn giao.
                    </p>

                </form>

            </div>

        </div>

        <div class="card">

            <div class="card-body">

                <div class="eyebrow">
                    C03 · Cấp phát sạc điện
                </div>

                <h2>Xem trước lịch sạc</h2>

                <p class="muted spaced">
                    Xây dựng kế hoạch dựa trên nhu cầu sạc hiện tại,
                    khả năng tương thích của cổng sạc,
                    dữ liệu quan sát còn mới và giới hạn công suất
                    của từng trạm.

                    Khi xác nhận, hệ thống sẽ kiểm tra lại
                    phiên bản dữ liệu hiện tại.
                </p>

                <div class="record-actions">

                    ${actionButton(
                        'Tạo phương án lịch sạc',
                        'schedule_preview',
                        {},
                        ''
                    )}

                </div>

                <div class="records spaced">

                    ${list('plans')
                        .filter(p => p.kind !== 'capacity')
                        .slice()
                        .reverse()
                        .map(p => `

                        <article class="record">

                            <div class="row-spread">

                                <span class="record-id">
                                    ${esc(p.id)}
                                </span>

                                ${chip(p.status)}

                            </div>

                            <div class="record-actions">

                                <button
                                    class="secondary small"
                                    data-detail="plans"
                                    data-id="${esc(p.id)}"
                                >
                                    Xem chi tiết cấp phát
                                </button>

                                ${[
                                    'DRAFT',
                                    'PROPOSED',
                                    'PREVIEW'
                                ].includes(p.status)

                                    ? actionButton(
                                        'Xác nhận lịch sạc',
                                        'schedule_confirm',
                                        {plan_id: p.id},
                                        'small'
                                    )

                                    : ''}

                            </div>

                        </article>

                    `).join('') ||
                    '<p class="muted small-text">Chưa có phương án lịch sạc.</p>'}

                </div>

            </div>

        </div>

    </div>` +

    `<section class="card spaced">

        <div class="card-body">

            <h2>Lập lịch sạc cho đội xe</h2>

            ${fleetVehicles.length ? `

                <form
                    class="form spaced"
                    data-command="fleet_charge"
                >

                    <div class="form-row">

                        <label>
                            Xe dùng chung tại ô đỗ có sạc

                            <select name="vehicle_id" required>

                                ${fleetVehicles.map(v =>
                                    option(
                                        v.id,
                                        `${v.id} · ${v.spot_id} · ${v.soc}%`
                                    )
                                ).join('')}

                            </select>
                        </label>

                        <label>
                            Mức pin mục tiêu (%)

                            <input
                                type="number"
                                name="target_soc"
                                min="1"
                                max="100"
                                value="90"
                                required
                            >

                        </label>

                    </div>

                    <button type="submit">
                        Đăng ký sạc cho đội xe
                    </button>

                </form>

            ` : `
                <p class="muted spaced">
                    Xe dùng chung phải được đỗ tại ô có cổng sạc
                    tương thích trước khi lập lịch sạc.
                </p>
            `}

            <button
                class="link spaced"
                data-tab="charging"
            >
                Quản lý các phiên sạc →
            </button>

        </div>

    </section>` +

    `<div class="section-heading">

        <h2>Danh sách lệnh thiết bị</h2>

        <span class="muted small-text">
            Yêu cầu đã được lưu · Cần xác nhận
        </span>

    </div>

    <div class="records">

        ${commands.length
            ? commands.slice().reverse().map(c => `

            <article class="record">

                <div class="record-main">

                    <div>

                        <div class="record-title">

                            <h3>
                                ${esc(deviceCommandName(c.kind))}
                            </h3>

                            <span class="record-id">
                                ${esc(c.id)}
                            </span>

                        </div>

                        <div class="record-meta">

                            <span>
                                Hồ sơ ${esc(c.record_id)}
                            </span>

                            ${c.vehicle_id ? `
                                <span>
                                    Phương tiện ${esc(c.vehicle_id)}
                                </span>
                            ` : ''}

                            <span>
                                Tạo lúc ${date(c.created_at)}
                            </span>

                        </div>

                    </div>

                    ${chip(c.status)}

                </div>

                ${state.simulator && ![
                    'ACK',
                    'ACKNOWLEDGED',
                    'CONFIRMED',
                    'APPLIED',
                    'REJECTED',
                    'COMPLETED'
                ].includes(c.status) ? `

                    <div class="record-actions">

                        ${actionButton(
                            'Mô phỏng ACK',
                            'simulate',
                            {
                                command_id: c.id,
                                outcome: 'ACK'
                            },
                            'small'
                        )}

                        ${actionButton(
                            'Mô phỏng từ chối',
                            'simulate',
                            {
                                command_id: c.id,
                                outcome: 'REJECT'
                            },
                            'danger small'
                        )}

                        ${actionButton(
                            'Mô phỏng kết quả không xác định',
                            'simulate',
                            {
                                command_id: c.id,
                                outcome: 'UNKNOWN'
                            },
                            'secondary small'
                        )}

                    </div>

                    <p class="muted small-text spaced">
                        Chỉ sử dụng bằng chứng mô phỏng.
                        Không kết nối với thiết bị vật lý.
                    </p>

                ` : ''}

            </article>

        `).join('') : empty(
            'Không có yêu cầu thiết bị đang chờ',
            'Các lệnh bàn giao phương tiện và sạc điện được ghi nhận tại đây.'
        )}

    </div>` +

    (state.simulator ? `

        <section class="sim-area spaced">

            <div class="row-spread">

                <div>

                    <div class="eyebrow">
                        Môi trường kiểm thử có kiểm soát
                    </div>

                    <h2>Điều khiển dữ liệu mô phỏng</h2>

                </div>

                ${actionButton(
                    'Làm mới dữ liệu mô phỏng',
                    'sim_refresh',
                    {},
                    'secondary small'
                )}

            </div>

            <p class="muted small-text spaced">
                Chức năng làm mới chỉ cập nhật dữ liệu quan sát
                mô phỏng. Các thao tác tạo sự cố được sử dụng
                để kiểm tra điều kiện khả dụng và xử lý lỗi.

                Các chức năng này chỉ được bật khi máy chủ
                khởi động với tham số --simulator.
            </p>

            <form
                class="form spaced"
                data-command="sim_observe"
            >

                <div class="form-row">

                    <label>
                        Tài nguyên

                        <select name="resource_ref">

                            ${[
                                'ports',
                                'vehicles',
                                'spots'
                            ].flatMap(key =>
                                list(key).map(r =>
                                    option(
                                        `${key}:${r.id}`,
                                        `${
                                            {
                                                ports: 'Cổng sạc',
                                                vehicles: 'Phương tiện',
                                                spots: 'Ô đỗ'
                                            }[key]
                                        } · ${r.id}`
                                    )
                                )
                            ).join('')}

                        </select>
                    </label>

                    <label>
                        Tình trạng kỹ thuật

                        <select name="health">

                            ${option(
                                'OUT_OF_SERVICE',
                                'Ngừng hoạt động'
                            )}

                            ${option(
                                'OPERABLE',
                                'Hoạt động bình thường'
                            )}

                        </select>
                    </label>

                </div>

                <button
                    type="submit"
                    class="secondary"
                >
                    Gửi dữ liệu quan sát mô phỏng
                </button>

            </form>

        </section>

    ` : '') +

    `<div class="section-heading">

        <h2>Yêu cầu hỗ trợ chưa giải quyết</h2>

        <button
            class="link"
            data-tab="support"
        >
            Xem yêu cầu hỗ trợ →
        </button>

    </div>

    <p class="muted">

        ${list('incidents').filter(i =>
            !['RESOLVED', 'CLOSED'].includes(i.status)
        ).length}

        yêu cầu hỗ trợ cần được xem xét.

        <button
            class="link"
            data-tab="network"
        >
            Mở trang quản lý đội xe →
        </button>

    </p>`;
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
        return value ? 'Có' : 'Không';
    }

    if (Array.isArray(value)) {
        return value.length
            ? `<ol class="detail-items">
                ${value.map(item =>
                    `<li>${detailValue(item)}</li>`
                ).join('')}
               </ol>`
            : '<span class="muted">Không có</span>';
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
                new Date(value * 1000).toLocaleString(
                    'vi-VN',
                    {
                        day: '2-digit',
                        month: '2-digit',
                        year: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit',
                        hour12: false
                    }
                )
            );
        }

        if ([
            'soc',
            'target_soc',
            'declared_soc'
        ].includes(key)) {
            return `${esc(value)}%`;
        }
    }

    if ([
        'status',
        'health',
        'state',
        'freshness',
        'plug',
        'power'
    ].includes(key)) {
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

                    <dt>
                        ${esc(fieldName(key))}
                    </dt>

                    <dd>
                        ${detailValue(value, key)}
                    </dd>

                </div>

            `).join('')}

           </dl>`

        : '<p class="muted">Không có dữ liệu bổ sung.</p>';
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
            ? 'CreatedĐã tạo mới'
            : change.after == null
              ? 'Đã xóa'
              : 'Đã cập nhật';

        return `
          <section class="detail-change">
            <div class="row-spread">
              <h3>${esc(recordTypeName(change.kind))}</h3>
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
                     Phương tiện: ${esc(record.vehicle_id)}
                   </p>`
                : ''
            }

            ${
              rows.length
                ? `<div class="table-wrap spaced">
                    <table class="detail-diff">
                      <thead>
                        <tr>
                          <th>Trường dữ liệu</th>
                          <th>Trước thay đổi</th>
                          <th>Sau thay đổi</th>
                        </tr>
                      </thead>

                      <tbody>
                        ${rows.map(row => `
                          <tr>
                            <th scope="row">
                              ${esc(fieldName(row.key))}
                            </th>
                            <td>${row.old}</td>
                            <td>${row.next}</td>
                          </tr>
                        `).join('')}
                      </tbody>
                    </table>
                  </div>`
                : `<p class="muted">
                     Không có thay đổi dữ liệu hiển thị.
                   </p>`
            }
          </section>
        `;
      }).join('')
    : '<p class="muted">Không có thay đổi dữ liệu được ghi nhận.</p>';
}

function activityHistory() {
    const records = list('audit')
        .slice()
        .reverse();

    return heading(
        'Minh chứng và lịch sử',
        'Lịch sử hoạt động',
        'Xem lại các thao tác đã được ghi nhận và những thay đổi dữ liệu trong hệ thống.'
    ) + (
        records.length
            ? `

                <div class="table-wrap">

                    <table>

                        <thead>

                            <tr>
                                <th>Thời gian</th>
                                <th>Người thực hiện</th>
                                <th>Thao tác</th>
                                <th>Chi tiết</th>
                            </tr>

                        </thead>

                        <tbody>

                            ${records.map(a => `

                                <tr>

                                    <td>
                                        ${date(a.at)}
                                    </td>

                                    <td>

                                        ${esc(
                                            a.actor_id ||
                                            a.actor ||
                                            'Hệ thống'
                                        )}

                                    </td>

                                    <td>

                                        ${esc(
                                            actionName(
                                                a.action || a.kind
                                            )
                                        )}

                                    </td>

                                    <td class="history-detail">

                                        ${auditChanges(a).length
                                            ? `

                                                <span class="small-text muted">

                                                    ${auditChanges(a).length}
                                                    bản ghi

                                                </span>

                                                <br>

                                                <button
                                                    type="button"
                                                    class="secondary small"
                                                    data-detail="audit"
                                                    data-id="${esc(a.id)}"
                                                >
                                                    Xem thay đổi
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
                'Chưa có hoạt động được ghi nhận',
                'Thực hiện một lượt đặt chỗ hoặc gửi yêu cầu để bắt đầu ghi nhận lịch sử.'
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
  else if (button.id==='logout') {refreshVersion++;try {await request('/api/logout',{});refreshVersion++;state=null;notice.hidden=true;window.history.replaceState(null,'',location.pathname);renderLogin();}catch(error){showNotice(apiErrorText(error), true);}}
  else if (button.dataset.detail) {
    const record = find(
      button.dataset.detail,
      button.dataset.id
    );

    const content = document.querySelector(
      '#detail-content'
    );

    if (!record) {
      return showNotice(
          'Không tìm thấy hồ sơ.',
          true
      );
    }

    content.innerHTML =
      button.dataset.detail === 'audit'
        ? `
          <h2>
            Chi tiết hoạt động —
            ${esc(actionName(record.action || record.kind))}
          </h2>

          <p class="muted spaced">
            ${esc(
              record.actor_id ||
              record.actor ||
              'Hệ thống'
            )}
            · ${esc(date(record.at))}
          </p>

          ${auditDetail(record)}
        `
        : `
          <h2>Chi tiết phương án cấp phát</h2>

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
    catch(error) {
        document.querySelector('#login-error').textContent =
            apiErrorText(error);
    }
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
