# Smart E-Mobility Hub

Ứng dụng demo chạy cục bộ cho bốn phân hệ A–D. Giao diện, tài khoản và cơ sở dữ liệu SQLite dùng chung. Một xe được điều chuyển sẽ đồng thời thay đổi khả năng cho thuê, sức chứa của hai hub và khả năng xếp lịch sạc.

## Chạy ứng dụng

Cần Python 3.10 trở lên. Các lệnh sau chạy từ thư mục có tệp `README.md`. Trên Windows có thể dùng `py` thay cho `python`.

```sh
python -m pip install -r requirements.txt
python -m emobility.server --simulator
```

Mở <http://127.0.0.1:8000>. Lần chạy đầu tạo dữ liệu mẫu trong `data/hub.sqlite`. Các lần khởi động sau đọc lại dữ liệu đã lưu. Muốn trình diễn lại từ đầu, chỉ định một đường dẫn mới bằng `--db data/demo-moi.sqlite`.

| Tài khoản | Mật khẩu mặc định | Thao tác chính |
|---|---|---|
| `alice`, `bob` | `alice-demo`, `bob-demo` | A thuê/trả xe và hỗ trợ hành trình, B đặt chỗ/vào/ra bãi, C đăng ký và quản lý sạc xe cá nhân |
| `operator` | `operator-demo` | B xử lý thiếu chỗ, C lập lịch sạc, D giám sát, phát lệnh điều chuyển, giao việc bảo trì, mô phỏng nhu cầu và theo dõi IoT |
| `dispatcher` | `dispatcher-demo` | D thực hiện lệnh điều chuyển được giao và đề nghị bàn giao từng xe |
| `technician` | `technician-demo` | D ghi kết quả kiểm tra, khắc phục sự cố hoặc chuyển xưởng |

Có thể đặt mật khẩu riêng bằng biến môi trường, ví dụ `EMOBILITY_OPERATOR_PASSWORD`. Để thao tác nhiều tài khoản, dùng các hồ sơ trình duyệt riêng hoặc đăng xuất khi đổi người.

## Kịch bản trình diễn

1. **D → A/B.** Trong **Fleet operations → Transfers**, dùng `operator` để lập và phát hành lệnh chuyển V1 và V3 từ H1 đến H2 trên bộ dữ liệu mới. Với `dispatcher`, bắt đầu lệnh rồi yêu cầu bàn giao V1. Trong **Operations**, `operator` chọn **Simulate ACK** cho yêu cầu bàn giao. Làm mới trang để thấy V1 tại H2, chỗ cũ được giải phóng, lệnh còn mở cho V3. Bàn giao và xác nhận V3 để hoàn tất. Sinh viên có thể thuê lại xe ngay khi xe đủ điều kiện tại hub đích.
2. **D → C.** Khi lập lệnh điều chuyển, chọn chỗ đích có sạc. Sau khi xác nhận bàn giao, dùng **Operations** để đặt sạc xe đội tại chỗ đó. Với xe cá nhân, dùng `alice`, mở **Parking**, chọn P1 và tích **Include charging**. Xuất trình QR rồi dùng Technical simulator để quét và cung cấp bằng chứng arrival/kết nối. Hệ thống khởi tạo sạc khi đủ điều kiện, chờ ACK cấp điện; xem luồng mô phỏng chi tiết bên dưới.
3. **D → bảo trì.** Trong **Fleet operations → Maintenance**, dùng `operator` để mở phiếu cho một trụ sạc. Trụ bị cô lập ngay. Đăng nhập `technician`, ghi kết quả và xác nhận kiểm tra an toàn để đưa trụ trở lại phục vụ, hoặc chuyển xưởng và giữ trạng thái cô lập.
4. **D → dự báo.** Trong **Demand forecast**, thử H1 với hệ số 3 trên bộ dữ liệu mới. Xem mức chiếm dụng dự kiến và tạo bản nháp từ khuyến nghị nếu có xe và chỗ phù hợp. Việc phát hành lệnh sẽ kiểm tra lại tài nguyên.
5. **A → B.** Dùng `alice` giữ xe từ **Explore hubs**, mở QR trong **My journeys** để thiết bị quét và xác nhận bàn giao. Sau ACK, hành trình mở. Chọn Hub trả bằng Save return destination; sự kiện thiết bị RETURN mới đóng chuyến. Chủ xe có thể xem yêu cầu hỗ trợ và trả lời phương án tiếp nhận của điều hành.

Nếu dữ liệu quan sát cũ hơn 90 giây, dùng **Operations → Refresh simulated observations** với tài khoản điều hành. Quyền giữ chỗ, bàn giao, sự cố và yêu cầu nhận ACK vẫn được lưu qua lần làm mới và khởi động lại.

## Phát dữ liệu IoT mẫu

Trong cửa sổ terminal thứ hai, chạy lệnh dưới đây khi máy chủ đang bật `--simulator`. Trang **Fleet operations → Telemetry** hiển thị gói gần nhất sau khi làm mới. Nguồn mẫu từ phần D được ánh xạ theo mã xe hiện có, ví dụ V01 thành V1.

```sh
python -m emobility.telemetry_simulator --count 3 --interval 2 --anomaly LOW_BATTERY
```

Công cụ cũng hỗ trợ `OVERSPEED`, `RAPID_DRAIN` và `INVALID_ID`. Máy chủ lưu dấu sự kiện để phát hiện gói trùng, gói cũ và các thay đổi bất thường trong cửa sổ 30 giây. Đích đến do xe báo được dùng cho dự báo; vị trí đỗ chỉ đổi khi có bằng chứng bàn giao.

## Kiểm thử

```sh
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
python tests/ui_button_audit.py --report tests/ui_audit_results.json
```

Kiểm thử UI cần Chrome. Bộ test dùng database tạm và browser context riêng cho từng tài khoản; ảnh QR thực sự được giải mã trong test bằng `zxing-cpp`.

## Charging only và QR nhận xe

Tab **Charging** hỗ trợ đặt sạc trực tiếp với đúng năm dữ liệu: xe cá nhân, Hub, SOC hiện tại do người dùng khai báo, SOC mục tiêu và giờ đến. Không cần đặt Parking trước. Yêu cầu ở trạng thái `PENDING` và chưa giữ tài nguyên. Operator mở **Operations**, xem đề xuất vị trí/cổng, năng lượng, công suất, thời lượng và giờ nhận xe dự kiến rồi chọn **Confirm charging proposal** hoặc nhập lý do để từ chối.

Khi xác nhận, backend kiểm tra lại quyền sở hữu, trạng thái tài nguyên, lịch đỗ/sạc và công suất. Quyền đỗ và phiên sạc được cấp trong cùng transaction SQLite; chỉ khi thành công mới chuyển `BOOKED` và cấp QR. SOC khai báo được lưu riêng, không ghi đè SOC quan sát của xe. Ước tính dùng dung lượng pin × chênh lệch SOC / (công suất × hiệu suất 90%). Không tự đổi Hub hay đẩy lịch sang thời điểm khác khi hết tài nguyên.

Sau khi Operator xác nhận, sinh viên mở **Show charging QR** và xuất trình tại vị trí được cấp. Thiết bị xác minh QR rồi gửi bằng chứng arrival/kết nối; hệ thống tự gửi START khi đủ điều kiện. UI tự cập nhật mỗi 4 giây khi trang đang hiển thị, giữ nội dung form đang nhập. Sinh viên có thể dùng **Stop charging** để chủ động dừng sớm. Khởi động lại server để tải mã mới; dữ liệu cũ được giữ nguyên. Cách thử bằng thiết bị mô phỏng được mô tả bên dưới.

Hủy yêu cầu pending không ảnh hưởng tài nguyên. Hủy booking chưa check-in giải phóng cả quyền đỗ và phiên sạc, vô hiệu hóa QR. Khi đã tiếp nhận hoặc đang chờ bằng chứng tiếp nhận, hệ thống bảo vệ chỗ đỗ; phải hoàn tất quy trình rút cáp/rời bãi. Trạng thái `COMPLETED` hiển thị lời nhắc nhận xe, không tự làm trống bay.

Trong **My journeys**, giữ xe thành công theo quy trình hiện có sẽ cấp **Show rental QR**. Mã gắn với lượt giữ, chủ tài khoản, xe, Hub nhận và hạn 10 phút. Sinh viên chỉ xuất trình QR; thiết bị khởi tạo PICKUP, hành trình chỉ mở sau ACK. **Save return destination** lưu Hub đích và quyền đỗ tùy chọn, không xác nhận đã trả xe. Thiết bị chuẩn bị tiếp nhận và gửi bằng chứng RETURN để đóng chuyến đi. Mã sai, đã hủy/hết hạn hoặc không đúng xe/Hub/bay bị từ chối; xử lý lặp không tạo thêm bàn giao.

Kiểm thử thủ công bốn loại đặt chỗ, dùng database demo mới và hai hồ sơ trình duyệt cho `alice`/`operator`:

1. **Parking only:** Parking → P1, H2, giờ đến hiện tại, giờ đi sau một giờ, bỏ chọn Include charging. Kiểm tra chỉ có quyền đỗ, xem Parking QR và thực hiện arrival/departure với ACK.
2. **Parking & Charging:** Parking → chọn Include charging và SOC mục tiêu. Kiểm tra quyền đỗ và phiên sạc tạo cùng nhau; vẫn dùng Parking QR để vào bãi.
3. **Charging only:** Charging → P1, H1, SOC 30→80, giờ đến hiện tại. Kiểm tra chưa có QR khi pending; Operator xác nhận; UI tự hiện bay, port, lịch và QR. Thử riêng cả từ chối có lý do và hủy trước check-in.
4. **Add charging:** Tạo Parking only tại bay có cổng tương thích, chọn quyền đó trong Charging → Add charging. Kiểm tra chỉ thêm phiên sạc. Hủy phiên và kiểm tra quyền đỗ ban đầu vẫn còn. Có thể chọn bay tường minh qua API `reserve_parking` khi cần fixture xác định; giao diện Parking hiện tự cấp bay, ưu tiên bay thường.

Các lệnh kiểm chứng (Python 3.10+, Chrome cho test UI):

```sh
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
python tests/ui_charging_reservations.py
python tests/ui_iot_workflow.py
python tests/ui_button_audit.py --report tests/ui_audit_results.json
```

Chi tiết thay đổi: [charging_requests.py](emobility/charging_requests.py) quản lý pending/duyệt/từ chối/hủy, phân bổ và QR sạc; [rental_qr.py](emobility/rental_qr.py) tạo QR thuê; [domain.py](emobility/domain.py) nối các nghiệp vụ, metadata loại đặt chỗ và migration QR cho lượt giữ cũ; [server.py](emobility/server.py) phục vụ API QR và asset mới; [active_services.py](emobility/active_services.py) tính yêu cầu pending. Giao diện ở [service-bookings.js](web/service-bookings.js), [app.js](web/app.js), [index.html](web/index.html) và [styles.css](web/styles.css). Test bổ sung ở [test_charging_requests.py](tests/test_charging_requests.py), [test_rental_qr.py](tests/test_rental_qr.py), [test_http_integration.py](tests/test_http_integration.py), [ui_charging_reservations.py](tests/ui_charging_reservations.py).

Kiểm chứng sau cập nhật IoT trên Windows/Python 3.13 và Chrome: **117 unittest đạt**, **110 bước IoT UI đạt** và **86 bước hồi quy Charging/QR đạt**. Bộ IoT UI thao tác qua form Technical simulator thật, kiểm tra không có nút vật lý của sinh viên, xác minh QR không tạo bằng chứng, tự gửi START nhưng vẫn chờ ACK, trả xe, departure, Add charging không check-in lại, polling không cần Refresh và giữ nội dung đang nhập. Bộ Charging/QR giải mã ảnh QR thực trên desktop/mobile. Các test API cũ vẫn chạy để bảo vệ tương thích. Xem [kết quả IoT UI](tests/iot_ui_results.json), [kết quả Charging/QR](tests/charging_ui_results.json) và [bộ hồi quy đầy đủ](tests/ui_audit_results.json). Các FINDING trong báo cáo là hạn chế giao diện còn mở, không được tính là PASS.

Database giữ kiến trúc bảng documents/receipts/events hiện có, bổ sung collection `charge_requests` và metadata `PARKING_ONLY`, `PARKING_AND_CHARGING`, `CHARGING_ONLY`, `ADD_CHARGING` cho bản ghi mới. Không thay hoặc xóa database; QR thuê được bổ sung cho lượt giữ cũ còn hiệu lực khi khởi động. Token được sinh tại backend, lưu bền, ảnh QR sinh cục bộ.

Giới hạn: cấp lịch tại giờ đến đã chọn, không tự tối ưu sang giờ khác hoặc chia nhỏ công suất còn dư giữa các phiên. Chính sách hiện có vẫn giữ tối thiểu 15 phút đỗ, tối đa 12 giờ và buffer 15 phút; giờ nhận xe hiển thị theo kết thúc sạc dự kiến. Các đề xuất chưa duyệt không giữ chỗ và có thể không còn khả thi khi xác nhận. Thông báo nhận xe nằm trong ứng dụng, chưa có email/push. Chưa tích hợp camera hoặc đầu đọc tại cổng. Các tác động vật lý vẫn phụ thuộc Role D/IoT; ACK trong demo mang nhãn simulated. Bản preview độc lập trong `deploy-demo` chưa có luồng backend mới.

## Luồng QR và IoT Simulator

Lần chạy hồi quy đầy đủ cuối cùng: **539 bước PASS, 0 FAIL, 6 FINDING**. Sáu hạn chế cũ còn lại: UI chưa chọn bay cụ thể, chưa preview khả dụng theo giờ, chưa tách số bay thường/bay sạc, chưa gợi ý Hub thay thế khi đầy, vẫn hiện form đăng ký xe cho Operator dù backend từ chối, và thiếu cảnh báo tổng quát riêng cho dữ liệu stale. Polling đã được kiểm chứng và không còn là FINDING.

Trước đây sinh viên bấm request cho từng thao tác vật lý. Nay sinh viên chỉ đăng ký, xem QR, lưu Hub trả xe và theo dõi trạng thái. Đã bỏ các nút Request pickup/arrival/departure/return/plug-in/unplug/start, nút gửi scan trong popup QR và form nhập mã check-in của sinh viên. Nút Stop charging được giữ để chủ động dừng sớm; đăng ký, hủy và xem QR vẫn giữ nguyên. Chính sách duyệt booking, phân bổ tài nguyên, thời lượng sạc, hủy và timeout không đổi.

Chạy server với `--simulator`, mở hai hồ sơ trình duyệt cho sinh viên và `operator`. Tab **Technical simulator** chỉ xuất hiện cho Operator khi simulator bật. Đây là công cụ kỹ thuật đóng vai thiết bị, không phải bước duyệt nghiệp vụ bổ sung:

1. Sinh viên mở QR. Trong **Technical simulator → Simulate a QR reader**, nhập token, xe, Hub và bay đúng như booking rồi bấm **Simulate QR scan**. Mã sai vị trí bị từ chối. Quét hợp lệ chỉ tạo command PICKUP/ARRIVAL đang chờ; chưa đổi trạng thái vật lý.
2. Trong **Operations**, phát **Simulate ACK** cho PICKUP hoặc ARRIVAL để mô phỏng bằng chứng bàn giao thật. Trang sinh viên tự cập nhật; không bấm Refresh hay xác nhận bổ sung. Nếu chưa có ACK, xe/chỗ vẫn giữ trạng thái chờ theo chính sách cũ.
3. Đối với sạc, chọn sự kiện **PLUG** trong **Technical simulator → Simulate physical evidence**, chọn session tương ứng và kiểm tra xe/Hub/bay/port. **Submit simulated event** xác nhận kết nối mô phỏng. Nếu đã đến giờ và thỏa các kiểm tra an toàn hiện có, hệ thống tạo START_PENDING; chỉ ACK START mới chuyển CHARGING. Nếu chưa đến giờ, maintenance tick sẽ kiểm tra lại. ACK START bị từ chối không gây vòng lặp gửi START tự động; cần xử lý nguyên nhân và cung cấp sự kiện kết nối hợp lệ mới để thử lại.
4. Hệ thống tạo STOP_PENDING khi đạt điều kiện hoàn thành hiện có (SOC quan sát đạt mục tiêu hoặc đến cuối lịch), hoặc sinh viên chọn Stop charging. Phát ACK STOP. Sau đó phát **UNPLUG** cho session và **DEPARTURE** cho visit. Hoàn thành sạc và rút cáp vẫn không tự giải phóng bay; chỉ bằng chứng departure hợp lệ mới làm việc đó.
5. Trả xe thuê: sinh viên **Save return destination**. Simulator phát **RETURN_PREPARE** với trip/xe/Hub đã chọn (chưa cần bay); bước này gọi logic tiếp nhận hiện có và trả về `return_right_id`. Chọn lại trip để form điền bay đã cấp, rồi phát **RETURN** tại bay đó. Chỉ sự kiện RETURN hợp lệ mới đóng chuyến đi. Nếu hết chỗ, quy trình hỗ trợ hiện có vẫn giữ chuyến đi mở.
6. Add charging dùng đúng right/visit đã có, không quét check-in lần hai; phát PLUG cho session bổ sung. Khi dữ liệu quan sát STALE, dùng Refresh simulated observations như trước; thao tác làm mới không phải bằng chứng arrival/connection.

[iot_workflow.py](emobility/iot_workflow.py) là lớp điều phối mới. Nó gọi lại `do_scan_rental`, `do_scan_charge`, `do_arrive`, `do_return_vehicle`, `do_plug`, `do_unplug`, `do_depart`, `do_start_charge` và `do_simulate`; không thay thuật toán cấp bay/công suất. Tích hợp tối thiểu trong [domain.py](emobility/domain.py) chạy điều phối sau command và maintenance tick, cùng metadata `iot_managed`/`iot_start_requested` và Hub trả xe được chọn. Event ID được lưu trong bảng events hiện có để replay bền và phát hiện payload mâu thuẫn. Không thêm bảng hoặc xóa API cũ.

Các file giao diện thay đổi ở [app.js](web/app.js), [parking-qr.js](web/parking-qr.js), [service-bookings.js](web/service-bookings.js). Test mới: [test_iot_workflow.py](tests/test_iot_workflow.py), [ui_iot_workflow.py](tests/ui_iot_workflow.py). Hai bộ [ui_button_audit.py](tests/ui_button_audit.py) và [ui_charging_reservations.py](tests/ui_charging_reservations.py) cập nhật theo QR chỉ xuất trình; các kiểm tra API request cũ được đánh dấu `LEGACY_HTTP_API`, không được báo là click UI sinh viên. Bộ IoT UI kiểm chứng đường đi qua form kỹ thuật thật và tự cập nhật không Refresh.

Ranh giới Role D: adapter hiện chỉ nhận **SIMULATED**, được bảo vệ bằng tài khoản Operator và cờ simulator. Chưa có xác thực thiết bị thật, khóa thiết bị, chữ ký telemetry hoặc camera scanner. Thiết bị thật cần adapter được xác thực và ràng buộc scope từ cấu hình đáng tin cậy; không dùng trực tiếp tài khoản Operator ngoài môi trường demo. UI kỹ thuật nhập scope để kiểm thử và backend đối chiếu với booking. Quét QR hoặc mở popup không tự tạo bằng chứng vật lý.

## Bộ đếm dịch vụ và QR đỗ xe (chi tiết)

`Your active services` lấy trực tiếp từ `active_services` của `/api/state`, tính theo tài khoản đã xác thực. Giữ xe chuyển thành chuyến đi chỉ tính một lượt; quyền đỗ chuyển thành visit chỉ tính một lượt. Gói đỗ + sạc đặt chung tính một gói cho đến khi cả việc đỗ và các nghĩa vụ sạc/kết nối đã kết thúc. Sạc đăng ký riêng trên một quyền đỗ độc lập vẫn là dịch vụ riêng. Xe đội đã trả về Hub không còn là dịch vụ của sinh viên dù vẫn chiếm chỗ đỗ vật lý.

Sau khi đặt chỗ, vào **Parking → Show parking QR** để xem QR, mã xác nhận, xe, Hub, bay, giờ đến và hạn check-in. QR được sinh cục bộ bằng thư viện [qrcode](https://pypi.org/project/qrcode/), không gửi mã tới dịch vụ bên ngoài. Sinh viên xuất trình QR; thiết bị xác minh và xác nhận arrival trước khi bay thành OCCUPIED. Departure do sự kiện thiết bị xác nhận qua luồng Simulator mô tả phía trên.

Mã ngẫu nhiên được lưu cùng quyền đỗ và không đổi sau refresh/restart. Hủy/hết hạn làm mã không còn hiệu lực; HANDOVER_PENDING giữ yêu cầu chờ đối soát; CONSUMED không thể tạo visit thứ hai. Hạn yêu cầu vào đỗ vẫn theo quy tắc hiện có: giờ đến + 10 phút; đến sớm được kiểm tra lại xung đột. Thời hạn này không tự giải phóng bay đã có xe hoặc yêu cầu bàn giao chưa rõ kết quả.

Khi chạy phiên bản mới trên database cũ, ứng dụng bổ sung QR cho quyền chưa dùng/đang chờ, không xóa quyền, lịch sử, receipt hoặc sự kiện. Khởi động lại máy chủ để nạp mã mới; không cần xóa database. Các tính năng này áp dụng cho ứng dụng Python/SQLite tại localhost; `deploy-demo/index.html` là preview mô phỏng độc lập, không có backend cấp QR.

Để kiểm chứng: đặt chỗ thường bằng `alice`, xem bộ đếm là 1, mở QR, mô phỏng quét QR và ACK arrival; UI Alice tự cập nhật, bộ đếm vẫn 1. Sau sự kiện DEPARTURE hợp lệ, bộ đếm về 0. `bob` không thấy quyền hoặc dịch vụ của Alice. Nếu tài nguyên bị STALE, dùng **Refresh simulated observations** trước khi thử giao dịch; thao tác này không tạo ACK.

Bộ kiểm thử tạo cơ sở dữ liệu tạm. Các ca bao gồm tranh chấp xe, giữ chỗ và sạc trong một giao dịch, bàn giao từng phần, sự cố và sửa chữa, phân quyền, gói lặp, mất phản hồi và khởi động lại. Các ca HTTP dùng cùng đường đăng nhập, truy vấn trạng thái và gửi lệnh với giao diện web.

## Phạm vi tích hợp

Mã A/B/C nằm trong `emobility/domain.py`. Các luồng D02/D03/D06 nằm trong `emobility/operations.py`; D01/D04/D05/D07 nằm trong `emobility/monitoring.py`. Nghiệp vụ điều chuyển, bảo trì, dự báo, cảnh báo và mẫu dữ liệu được chuyển thể từ phần D của Phan Ngọc Xuân Lợi. Các phân hệ dùng chung mã tài nguyên, giao dịch SQLite, phiên đăng nhập và nhật ký. Tài liệu nộp gốc cùng prototype có trong `docs/` và `prototype/`.

Bản này phục vụ trình diễn trên localhost. Các ACK và dữ liệu IoT mẫu mang nhãn mô phỏng. Khi chạy thiếu `--simulator`, bộ phát và nút tạo bằng chứng bị tắt. Việc xác nhận trực tiếp từ xe, cảm biến chỗ đỗ và trụ sạc thật cần bộ kết nối thiết bị tại điểm triển khai. Phiếu kiểm tra của kỹ thuật viên ghi nhận thông tin do nhân viên nhập.
