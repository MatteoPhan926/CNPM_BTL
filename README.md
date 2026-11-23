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
2. **D → C.** Khi lập lệnh điều chuyển, chọn chỗ đích có sạc. Sau khi xác nhận bàn giao, dùng **Operations** để đặt sạc xe đội tại chỗ đó. Với xe cá nhân, dùng `alice`, mở **Parking**, chọn P1 và tích **Include charging**. Xác nhận giữ chỗ rồi yêu cầu vào bãi. Trong **Charging**, lần lượt yêu cầu cắm, bắt đầu, dừng và rút sạc. Mỗi thao tác vật lý cần ACK riêng từ **Operations**; bắt đầu sạc trong khung giờ đã lên lịch.
3. **D → bảo trì.** Trong **Fleet operations → Maintenance**, dùng `operator` để mở phiếu cho một trụ sạc. Trụ bị cô lập ngay. Đăng nhập `technician`, ghi kết quả và xác nhận kiểm tra an toàn để đưa trụ trở lại phục vụ, hoặc chuyển xưởng và giữ trạng thái cô lập.
4. **D → dự báo.** Trong **Demand forecast**, thử H1 với hệ số 3 trên bộ dữ liệu mới. Xem mức chiếm dụng dự kiến và tạo bản nháp từ khuyến nghị nếu có xe và chỗ phù hợp. Việc phát hành lệnh sẽ kiểm tra lại tài nguyên.
5. **A → B.** Dùng `alice` giữ xe từ **Explore hubs**, rồi yêu cầu nhận xe trong **My journeys**. Sau ACK, hành trình mở. Yêu cầu trả xe sang hub khác và xác nhận ACK để đóng chuyến. Chủ xe có thể xem yêu cầu hỗ trợ và trả lời phương án tiếp nhận của điều hành.

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

## Bộ đếm dịch vụ và QR đỗ xe

`Your active services` lấy trực tiếp từ `active_services` của `/api/state`, tính theo tài khoản đã xác thực. Giữ xe chuyển thành chuyến đi chỉ tính một lượt; quyền đỗ chuyển thành visit chỉ tính một lượt. Gói đỗ + sạc đặt chung tính một gói cho đến khi cả việc đỗ và các nghĩa vụ sạc/kết nối đã kết thúc. Sạc đăng ký riêng trên một quyền đỗ độc lập vẫn là dịch vụ riêng. Xe đội đã trả về Hub không còn là dịch vụ của sinh viên dù vẫn chiếm chỗ đỗ vật lý.

Sau khi đặt chỗ, vào **Parking → Show parking QR** để xem QR, mã xác nhận, xe, Hub, bay, giờ đến và hạn check-in. QR được sinh cục bộ bằng thư viện [qrcode](https://pypi.org/project/qrcode/), không gửi mã tới dịch vụ bên ngoài. Có thể dùng **Request arrival** hoặc dán chuỗi đọc từ QR vào **Check in with a parking code**. QR chỉ xác nhận quyền yêu cầu tiếp nhận; vẫn cần **operator → Operations → Simulate ACK** cho ARRIVAL trước khi bay thành OCCUPIED. Sau đó, **Request departure** cũng cần ACK riêng.

Mã ngẫu nhiên được lưu cùng quyền đỗ và không đổi sau refresh/restart. Hủy/hết hạn làm mã không còn hiệu lực; HANDOVER_PENDING giữ yêu cầu chờ đối soát; CONSUMED không thể tạo visit thứ hai. Hạn yêu cầu vào đỗ vẫn theo quy tắc hiện có: giờ đến + 10 phút; đến sớm được kiểm tra lại xung đột. Thời hạn này không tự giải phóng bay đã có xe hoặc yêu cầu bàn giao chưa rõ kết quả.

Khi chạy phiên bản mới trên database cũ, ứng dụng bổ sung QR cho quyền chưa dùng/đang chờ, không xóa quyền, lịch sử, receipt hoặc sự kiện. Khởi động lại máy chủ để nạp mã mới; không cần xóa database. Các tính năng này áp dụng cho ứng dụng Python/SQLite tại localhost; `deploy-demo/index.html` là preview mô phỏng độc lập, không có backend cấp QR.

Để kiểm chứng: đặt chỗ thường bằng `alice`, xem bộ đếm là 1, mở QR, gửi Request arrival và xác nhận ACK bằng `operator`; quay lại Alice và Refresh, bộ đếm vẫn 1. Sau Request departure + ACK, bộ đếm về 0. `bob` không thấy quyền hoặc dịch vụ của Alice. Nếu tài nguyên bị STALE, dùng **Refresh simulated observations** trước khi thử giao dịch; thao tác này không tạo ACK.

Bộ kiểm thử tạo cơ sở dữ liệu tạm. Các ca bao gồm tranh chấp xe, giữ chỗ và sạc trong một giao dịch, bàn giao từng phần, sự cố và sửa chữa, phân quyền, gói lặp, mất phản hồi và khởi động lại. Các ca HTTP dùng cùng đường đăng nhập, truy vấn trạng thái và gửi lệnh với giao diện web.

## Phạm vi tích hợp

Mã A/B/C nằm trong `emobility/domain.py`. Các luồng D02/D03/D06 nằm trong `emobility/operations.py`; D01/D04/D05/D07 nằm trong `emobility/monitoring.py`. Nghiệp vụ điều chuyển, bảo trì, dự báo, cảnh báo và mẫu dữ liệu được chuyển thể từ phần D của Phan Ngọc Xuân Lợi. Các phân hệ dùng chung mã tài nguyên, giao dịch SQLite, phiên đăng nhập và nhật ký. Tài liệu nộp gốc cùng prototype có trong `docs/` và `prototype/`.

Bản này phục vụ trình diễn trên localhost. Các ACK và dữ liệu IoT mẫu mang nhãn mô phỏng. Khi chạy thiếu `--simulator`, bộ phát và nút tạo bằng chứng bị tắt. Việc xác nhận trực tiếp từ xe, cảm biến chỗ đỗ và trụ sạc thật cần bộ kết nối thiết bị tại điểm triển khai. Phiếu kiểm tra của kỹ thuật viên ghi nhận thông tin do nhân viên nhập.
