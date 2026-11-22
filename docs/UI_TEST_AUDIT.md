# Smart E-Mobility Hub — Báo cáo kiểm thử chức năng và giao diện

Kiểm thử ban đầu: 21/11/2026. Cập nhật sửa UI-01/UI-02 và hồi quy: 22/11/2026.

## Kết quả sau sửa bộ đếm và QR (22/11/2026)

Đã hiện thực cả hai tính năng trong ứng dụng Python/SQLite. Không triển khai Render, không thay tài khoản triển khai, không sửa/xóa database đang dùng. Mọi kiểm thử dùng SQLite tạm riêng và tài khoản demo trong process kiểm thử.

| Bộ kiểm thử | Trước sửa | Sau sửa |
|---|---|---|
| Backend/HTTP (`unittest discover`) | 59 PASS | **85 PASS, 0 lỗi** |
| UI Chrome/Playwright | 13 nhóm; 351 PASS, 10 FINDING, 0 FAIL | **15 nhóm; 505 PASS, 8 FINDING, 0 FAIL** |

Log trước sửa: [ui_audit_baseline.json](../tests/ui_audit_baseline.json). Log sau sửa: [ui_audit_results.json](../tests/ui_audit_results.json). Toàn bộ 34 action handler vẫn được kiểm qua UI; không xóa assertion cũ để làm test PASS. Hai kiểm tra UI-01/UI-02 chuyển từ finding sang assertion bắt buộc. UI-03…UI-10 vẫn là các finding ngoài phạm vi.

### Nguyên nhân và cách tính bộ đếm

Trước đây Overview chỉ cộng `holds`, `trips`, `sessions` tại frontend, bỏ sót `rights` và `visits`; không có phép gom nhóm dịch vụ. Bây giờ backend trả `active_services` từ cùng snapshot đã xử lý expiry, chỉ lấy bản ghi thuộc tài khoản đã xác thực. Frontend đọc trực tiếp số này sau mỗi giao dịch thành công và Refresh.

| Loại bản ghi | Trạng thái được tính |
|---|---|
| Hold | ACTIVE, HANDOVER_PENDING |
| Trip | OPEN, HANDOVER_PENDING, ASSISTANCE_PENDING |
| Parking right | CONFIRMED, HANDOVER_PENDING |
| Observed visit | PARKED, HANDOVER_PENDING |
| Charging session | BOOKED, START_PENDING, CHARGING, STOP_PENDING |

Không thêm trạng thái mới. CANCELLED, EXPIRED, COMPLETED, CLOSED, DEPARTED và quyền CONSUMED không được cộng như dịch vụ còn hoạt động. OFFERED chỉ là phương án phục hồi chưa được chấp thuận nên không tạo thêm số đếm.

- Hold/trip dùng chung khóa theo `hold_id`; right/visit dùng chung khóa theo `right_id`.
- Bundle nhận diện bằng `created_by_charge`/`created_parking`, gom parking và charging thành một nhóm. Phiên sạc đã COMPLETED không tự kết thúc cả gói: visit còn PARKED/HANDOVER_PENDING giữ nhóm active, và backend không cho rời bãi trước khi xử lý xong nghĩa vụ sạc/kết nối.
- Sạc đăng ký riêng trên quyền đỗ độc lập tính là dịch vụ riêng; hủy sạc không mất dịch vụ đỗ.
- Quyền tiếp nhận được liên kết bằng `trip.return_right_id` dùng chung nhóm chuyến khi đang trả xe. Visit của xe đội sau khi trip CLOSED không còn tính là dịch vụ của sinh viên; chỗ đỗ vật lý vẫn OCCUPIED đúng domain.
- Đặc tả hiện tại không định nghĩa phép đếm dashboard; áp dụng quy ước bundle trong yêu cầu lần này. Không thay đổi quy tắc thuê/đỗ/sạc.

### QR và ranh giới xác nhận tiếp nhận

Trước đây right chỉ có thông tin đặt chỗ, không có credential QR, API xem QR hay modal. Bây giờ mỗi quyền mới qua bộ cấp chỗ có mã ngẫu nhiên 256-bit với tiền tố `emobility:parking:`, thời điểm tạo và hạn đến (`start + 600 giây`). Metadata lưu trong document SQLite trong chính giao dịch đặt chỗ. Lỗi nghiệp vụ rollback cả right và QR; receipt replay trả lại giao dịch cũ, không tạo thêm quyền.

Migration bổ sung QR cho quyền cũ CONFIRMED/HANDOVER_PENDING/OFFERED thiếu QR, giữ nguyên các trường khác, receipt, lịch sử và sự kiện. Quyền cũ đã kết thúc không được tạo credential mới. Test kiểm tra dữ liệu trước/sau migration và khởi tạo lặp.

| Trạng thái quyền | Hành vi QR |
|---|---|
| CONFIRMED | Có thể yêu cầu tiếp nhận trong hạn; vẫn kiểm tra lại chủ sở hữu, phương tiện, Hub, độ mới, chỗ đỗ và xung đột |
| HANDOVER_PENDING | Chờ bằng chứng; quét lặp không tạo lệnh thứ hai, không tự hết hạn giải phóng claim |
| CONSUMED | Hiện đã dùng; từ chối tạo visit thứ hai |
| CANCELLED / EXPIRED | Hiện không hợp lệ và backend từ chối check-in |
| OFFERED | Chưa được dùng cho đến khi chủ quyền chấp thuận phương án |

`Show parking QR` mở modal với QR SVG thật được tạo cục bộ, ID, xe, Hub, bay, giờ đến, hạn và trạng thái; có Close. Không gọi dịch vụ QR ngoài. Có thể dán nội dung quét vào form `Check in with a parking code`, hoặc dùng Request arrival. Mã không chứa mật khẩu/PII, không thay thế đăng nhập hay kiểm tra quyền sở hữu. Shared rental vẫn dùng Request return.

Xác thực QR → tạo ARRIVAL pending → **operator chủ động Simulate ACK** → mới tạo observed visit và chuyển bay sang OCCUPIED. Hủy, hết hạn, mã sai hoặc mã của Bob/Alice khác đều bị chặn. ACK không được tự sinh. Modal cập nhật trạng thái mỗi 5 giây khi đang mở; lỗi reception hiển thị ngay trong modal; kết quả bất định vẫn dùng Retry same request hiện có.

### Bằng chứng kiểm thử mới

- 10 test bộ đếm: 0 ban đầu; đặt/hủy/hết hạn; pending quá hạn; right→visit→depart; hold→trip→return; bundle qua plug/start/stop/unplug/depart; sạc độc lập; đề xuất recovery; UNKNOWN/REJECT; Alice/Bob; snapshot/restart/replay.
- 15 test QR: entropy/định dạng và tính ổn định; rollback booking lỗi; chủ sở hữu; mã sai/thiếu; ràng buộc right; cancel/expiry; biên 600 giây; pending lâu; retry sau rejection; tranh chấp booking/scan; migration; xem QR không tạo command; đọc lại cùng mã trong **process Python mới**.
- Một test HTTP mới kiểm tra 401/403, bắt buộc mã, EMPTY trước ACK, CONSUMED sau ACK và không tạo visit thứ hai.
- Hai kịch bản UI mới kiểm tra toàn bộ acceptance counter, modal/Close, thông tin đặt chỗ, Refresh/restart service, nhập mã, trạng thái pending/consumed/cancelled/expired và báo lỗi ngay trong modal. QR trên màn hình được giải mã từ ảnh chụp bằng zxing-cpp ở desktop và viewport 390px; không chỉ kiểm tra có thẻ ảnh.
- Ảnh kiểm chứng: [desktop](../tests/artifacts/parking_qr_desktop.png), [mobile](../tests/artifacts/parking_qr_mobile.png). Modal mobile cuộn dọc để xem các nút phía dưới, không tràn ngang.

### Các file thay đổi

| File | Thay đổi |
|---|---|
| [active_services.py](../emobility/active_services.py) | Phép chiếu bộ đếm theo chủ sở hữu và khóa nhóm |
| [parking_qr.py](../emobility/parking_qr.py) | Cấp credential, tạo SVG cục bộ, tính trạng thái hiển thị QR |
| [domain.py](../emobility/domain.py) | Migration bổ sung, cấp QR trong transaction, xác thực arrival, snapshot counter |
| [server.py](../emobility/server.py) | API xem QR có xác thực và route JavaScript |
| [parking-qr.js](../web/parking-qr.js) | Modal, nhập mã, gửi yêu cầu, chống phản hồi cũ, trạng thái và lỗi |
| [app.js](../web/app.js), [index.html](../web/index.html), [styles.css](../web/styles.css) | Kết nối bộ đếm/API, nút/form/dialog và style theo giao diện hiện có |
| [test_active_service_counter.py](../tests/test_active_service_counter.py), [test_parking_qr.py](../tests/test_parking_qr.py) | Test mới dùng DB cô lập |
| [test_http_integration.py](../tests/test_http_integration.py) | Test API QR và ranh giới ACK |
| [test_adversarial.py](../tests/test_adversarial.py), [test_monitoring.py](../tests/test_monitoring.py) | Helper arrival gửi QR của quyền hiện có; giữ nguyên assertion |
| [ui_button_audit.py](../tests/ui_button_audit.py) | Assertion sửa lỗi, hai kịch bản mới, giải mã QR thực |
| [requirements.txt](../requirements.txt), [requirements-test.txt](../requirements-test.txt) | Dependency runtime và kiểm thử |
| [README.md](../README.md), báo cáo này và JSON/ảnh test | Hướng dẫn chạy, cơ chế, bằng chứng và hạn chế |

### Kiểm chứng bằng giao diện

1. Cài dependency và khởi động lại backend theo [README](../README.md); giữ nguyên đường dẫn database đang dùng, không xóa DB. Mở localhost, tải lại trang.
2. Alice → Parking → chọn P1, Hub, thời gian hợp lệ → Confirm reservation. Explore hubs hiển thị 1; Bob trên browser profile riêng vẫn 0 nếu chưa dùng dịch vụ.
3. Parking → Show parking QR: xem mã và thông tin, Close hoặc Request arrival. Lúc này bay vẫn chưa OCCUPIED.
4. Operator → Operations → Simulate ACK của ARRIVAL. Alice Refresh: có visit, bộ đếm vẫn 1. Request departure + ACK → bộ đếm 0.
5. Thử Include charging: bộ đếm luôn 1 khi còn đỗ/sạc, kể cả đã stop/unplug nhưng chưa departure. Hủy quyền chưa dùng → 0 và QR không còn hợp lệ.
6. Nếu tài nguyên quá hạn 90 giây, operator dùng Refresh simulated observations trước khi thử. Đây chỉ là làm mới quan sát mô phỏng, không phải ACK và không xóa quyền đặt chỗ.

Giới hạn: chưa tích hợp camera/scanner hoặc thiết bị IoT vật lý; nhập chuỗi QR và ACK mô phỏng là đường kiểm chứng hiện tại. Overview không polling thay đổi ở phiên người dùng khác (Refresh để lấy snapshot mới), riêng modal QR kiểm tra định kỳ. Preview HTML độc lập không có backend QR. Không nghiệm thu Render/TLS thật hay hiệu năng tải lớn.

## Phương pháp và phạm vi

- Chạy bộ `unittest` có sẵn (backend, SQLite, xử lý cạnh tranh, HTTP và các tình huống lỗi).
- Chạy Playwright trên Chrome thực, truy cập máy chủ HTTP Python ở loopback, sử dụng database SQLite tạm riêng cho từng kịch bản. Mỗi tài khoản có browser context riêng nhằm tách phiên đăng nhập.
- Click nút, nhập dữ liệu, kiểm tra HTTP response và trạng thái nghiệp vụ sau thao tác. Các ca kiểm tra lỗi hợp lệ (ví dụ đặt xe đã bị giữ) được tính PASS nếu hệ thống từ chối đúng, không tạo dữ liệu sai.
- Mô phỏng đồng hồ có kiểm soát để kiểm tra độ mới dữ liệu; không giả lập thành công của thiết bị thực. ACK được gửi rõ ràng từ giao diện operator.
- Tài khoản demo cục bộ dùng mật khẩu mặc định trong process test. Không dùng mật khẩu triển khai, không sửa `data/hub.sqlite`, không thao tác trên website từ xa.

## Kết quả tổng quan ban đầu (trước sửa, giữ để đối chiếu)

- Backend và tích hợp HTTP: **59/59 test PASS**.
- Ứng dụng chính: **11 kịch bản UI, 321 bước kiểm tra PASS, 10 điểm cần xử lý**. Không có bước chặn hoàn thành kịch bản và không phát hiện ngoại lệ JavaScript chưa xử lý trong các kịch bản này.
- Kiểm tra bổ sung: adapter `CloudHandler` chạy cục bộ kiểm tra health, đăng nhập/đọc trạng thái/đăng xuất 5 tài khoản và cookie Secure qua header giả lập proxy; preview HTML kiểm tra đăng nhập/đăng xuất 5 tài khoản, đặt xe và Reset demo. Tổng nhật ký cả 13 nhóm: **351 PASS, 10 FINDING, 0 FAIL**. Hai nhóm bổ sung không phải kiểm thử website Render thực tế hoặc toàn bộ chức năng của preview.
- **34/34 action handler nghiệp vụ** trong `domain.py`, `operations.py`, `monitoring.py` đã được kích hoạt qua giao diện. Đây là bao phủ các loại command, không phải chứng minh tất cả tổ hợp dữ liệu đầu vào đều đúng.
- `tests/ui_audit_results.json` chứa kết quả chi tiết từng bước, bao gồm các kiểm tra bổ sung cho adapter cloud và preview HTML. `tests/ui_button_audit.py` là script để tái hiện.

## Danh sách chức năng được kiểm thử

| UC/nhóm | Nút/điều khiển | Tài khoản | Kết quả kiểm tra chính |
|---|---|---|---|
| Đăng nhập | Sign in / Sign out | Cả 5 | PASS; menu đúng vai trò, sai mật khẩu bị từ chối, đăng nhập lại được |
| A01 | Refresh / All hubs / View vehicles | Alice, Bob | PASS; lọc đúng Hub; lưu ý dashboard chưa có thông tin tách loại chỗ đỗ |
| A02 | Reserve · 10 min | Alice, Bob | PASS; tranh chấp cùng xe bị từ chối đúng |
| A03 | Cancel reservation | Alice | PASS; hủy và giải phóng quyền giữ |
| A04 | Request pickup | Alice, Bob | PASS; chỉ mở chuyến sau ACK; reject có thể thử lại |
| A05 | Request return | Alice, Bob | PASS; cả walk-in lẫn quyền đỗ đặt trước; Hub hết chỗ giữ chuyến mở |
| A06 | My journeys / Activity | Alice, Bob | PASS; xem lịch sử; Alice không thấy chuyến của Bob |
| A07 | Send support request | Alice | PASS; tạo bản ghi hỗ trợ |
| A07/B05 | Accept proposed reception / Decline proposal | Alice | PASS; đồng ý thay quyền đỗ; từ chối không tự hoàn thành bàn giao |
| B01 | Register vehicle | Alice | PASS; operator thấy nhầm form nhưng backend chặn |
| B01 | Confirm reservation | Alice | PASS; đỗ thường, bundle sạc, xe thuê; hết chỗ từ chối đúng |
| B02 | Cancel unused right | Alice | PASS; hủy quyền chưa dùng |
| B03 | Request arrival | Alice | PASS; bay thành OCCUPIED sau ACK mô phỏng |
| B04 | Request departure | Alice | PASS; từ chối khi còn kết nối sạc; giải phóng sau ACK |
| B05 | Propose reception | Operator | PASS; đề xuất thay thế và chờ đồng ý |
| C01 | Reserve charging / Include charging | Alice | PASS; mục tiêu SOC không hợp lệ bị từ chối; quyền sạc độc lập cũng được xử lý |
| C02 | Request plug-in | Alice, Operator | PASS; từ chối khi xe chưa vào vị trí |
| C02 | Request start | Alice, Operator | PASS; không bật trước khi xác nhận kết nối |
| C02 | Request stop | Alice | PASS; ngắt điện không đồng nghĩa giải phóng chỗ đỗ |
| C02 | Request unplug | Alice | PASS; cập nhật ngắt kết nối |
| C02 | Cancel unused session | Alice | PASS; hủy bundle giải phóng quyền liên kết; bảo toàn quyền đỗ độc lập |
| C03 | Book fleet charging | Operator | PASS; đặt xe đội đã ở bay sạc |
| C03 | Create schedule preview / Review allocation / Close / Confirm schedule | Operator | PASS; xem chi tiết, phê duyệt |
| D01 | Inspect resources / Location / Deactivate / Reactivate | Operator | PASS; thay đổi tình trạng và hiển thị tài nguyên |
| D02 | Preview transfer / Issue transfer | Operator | PASS; chọn nguồn/đích, nhóm xe, chỗ sạc |
| D03 | Start transfer / Request handover | Dispatcher | PASS; bàn giao từng phần, reject và thử lại, đủ xe hoàn tất lệnh |
| D04 | Open maintenance ticket | Operator | PASS; cô lập thiết bị và giao phiếu kỹ thuật |
| D05 | Record outcome (Resolved / Escalated workshop) | Technician | PASS; nhánh sửa xong cần checkbox an toàn; chuyển xưởng giữ cô lập |
| D06 | Run forecast / Create transfer draft | Operator | PASS; dự báo tải, tạo nháp |
| D07 | Send simulated reading / Live updates | Operator | PASS; SOC và cảnh báo được cập nhật; đọc mới tự xuất hiện |
| D07 | Simulate ACK / Simulate rejection / Simulate unknown outcome | Operator | PASS; ba kết quả, không mặc nhiên coi yêu cầu là hành động vật lý |
| D07 | Refresh simulated observations / Submit synthetic observation | Operator | PASS; refresh phục hồi khả dụng; tạo và khôi phục lỗi mô phỏng |
| Khả năng phục hồi | Retry same request / Dismiss | Alice | PASS; phản hồi mất sau commit, retry không tạo lượt giữ thứ hai |
| Điều hướng | Find a vehicle / Reserve parking / Book parking + charging / Manage charging sessions / View support records / Open fleet operations / Open device outbox | Các vai trò liên quan | PASS |
| Responsive | 390px: 6 tab sinh viên | Alice | 5 tab không tràn chiều ngang; Charging bị tràn |
| Chế độ không simulator | Operations / Telemetry / Explore hubs | Operator, Alice | PASS; không có nút gửi bằng chứng giả; dữ liệu thiếu xác minh không cho thuê |

## Các lỗi hoặc khoảng trống xác nhận qua kiểm thử

| ID | Mức ưu tiên | Quan sát thực tế | Hướng xử lý |
|---|---|---|---|
| UI-01 | Đã sửa 22/11 | Trước sửa: đặt chỗ độc lập nhưng counter vẫn 0 | Đếm từ backend, gồm right/visit và gom nhóm; có test bắt buộc |
| UI-02 | Đã sửa 22/11 | Trước sửa: quyền chỉ trả ID, không có QR | QR thật, credential bền vững, xác thực yêu cầu arrival; ACK vẫn tách riêng |
| UI-03 | Cao | Form Parking không có bộ chọn `spot_id`, dù backend hỗ trợ | Cung cấp danh sách bay đủ điều kiện theo thời gian và phương tiện |
| UI-04 | Cao | Không có bước xem trước chỗ khả dụng theo khung giờ/đầu sạc | Thêm truy vấn không giữ chỗ, sau đó xác nhận lại atomic |
| UI-05 | Cao | Thẻ Hub không hiện riêng số chỗ thường và chỗ đỗ kèm sạc còn trống | Tính từ dữ liệu backend, biểu thị cả độ mới và chính sách 90% |
| UI-06 | Trung bình | Operator nhìn thấy form Register vehicle nhưng submit bị FORBIDDEN | Ẩn thao tác không phù hợp vai trò, giữ kiểm tra backend |
| UI-07 | Cao | Đặt chỗ ở Hub không tiếp nhận được trả HUB_CAPACITY nhưng không gợi ý Hub khác trước xác nhận | Đề xuất các Hub/phương án thay thế; không tạo quyền nếu không đủ điều kiện |
| UI-08 | Trung bình | Overview giữ snapshot cũ cho đến khi nhấn Refresh; chỉ telemetry có polling riêng | Cập nhật snapshot theo chu kỳ, không phá dữ liệu người dùng đang nhập |
| UI-09 | Trung bình | Sau 90 giây, Refresh làm số khả dụng chuyển 0; banner không giải thích rõ stale | Cảnh báo dữ liệu quá hạn, phân biệt hết chỗ với chưa xác minh; giữ chính sách an toàn |
| UI-10 | Trung bình | Charging ở viewport 390px có `document.scrollWidth = 522px` | Rà soát grid/cột/bảng, giới hạn chiều rộng và cuộn trong bảng |

UI-03, UI-04, UI-05, UI-07 liên quan cùng một nhóm cải thiện lựa chọn Hub/bay. UI-08 và UI-09 liên quan cơ chế hiển thị độ mới dữ liệu. Khoảng trống QR không có nghĩa thao tác arrival/departure hiện tại không chạy: luồng đó đã được kiểm qua mô phỏng.

## Chạy lại kiểm thử

Chạy từ thư mục gốc của dự án, sử dụng Python và Chrome:

```powershell
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
python tests/ui_button_audit.py --report tests/ui_audit_results.json
```

Ví dụ chỉ kiểm tra lại nhóm thuê xe và sạc:

```powershell
python tests/ui_button_audit.py rentals parking_charging
```

Kết quả `PASS` là kiểm tra đúng như mong đợi; `FINDING` là lỗi/khoảng trống phát hiện nhưng vẫn tiếp tục kiểm tra để bao phủ các hành trình còn lại; `FAIL` là assertion không thỏa khiến kịch bản đó bị dừng. Script trả exit code khác 0 nếu có `FAIL`.

## Giới hạn nghiệm thu

- Các ca tại thời điểm kiểm thử bao phủ command đang có và luồng chính cùng nhiều lỗi dự kiến, không chứng minh hoàn toàn không tồn tại lỗi.
- Chưa nghiệm thu website triển khai thực tế, mật khẩu triển khai, mạng Internet thật, TLS proxy thực, cảm biến IoT/barrier, bộ sạc vật lý hay hiệu năng tải lớn. Adapter cloud được kiểm tra cục bộ; preview HTML là bản mô phỏng riêng, không thay thế kết quả backend.
- Bản audit ban đầu chỉ bổ sung kiểm thử. Cập nhật 22/11 đã sửa đúng UI-01/UI-02 như phần đầu báo cáo; database đang dùng được giữ nguyên.
