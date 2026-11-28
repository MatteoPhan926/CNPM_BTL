# Smart E-Mobility Hub

Ứng dụng mô phỏng mạng trạm xe điện trong khu đô thị ĐHQG TP.HCM. Sinh viên có thể giữ xe, đặt chỗ đỗ và đăng ký sạc. Nhân viên điều phối theo dõi cùng mạng trạm, điều chuyển xe và xử lý sự cố. Điểm giao nhau giữa các nghiệp vụ là sức chứa thực tế của trạm. Một xe đã sạc xong vẫn chiếm chỗ cho đến khi hệ thống ghi nhận xe rời bãi.

## Chạy trên máy cá nhân

Cần Python 3.10 trở lên và trình duyệt web. Giải nén ZIP hoặc mở bản sao Git, sau đó chạy từ thư mục chứa `requirements.txt`.

**Linux và macOS**

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m emobility.server --simulator --auto-refresh
```

**Windows PowerShell**

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m emobility.server --simulator --auto-refresh
```

Mở [http://127.0.0.1:8000](http://127.0.0.1:8000). Lần chạy đầu tạo ba trạm mẫu trong `data/hub.sqlite`. Lần sau ứng dụng đọc lại tệp này. Muốn trình diễn trên dữ liệu mới, thêm `--db data/demo-moi.sqlite` và chọn tên tệp chưa dùng. Dừng máy chủ bằng `Ctrl+C`.

Ở chế độ cục bộ, đăng nhập bằng `alice` / `alice-demo` cho sinh viên và `operator` / `operator-demo` cho vận hành. Các tài khoản `bob`, `dispatcher` và `technician` dùng cùng quy ước mật khẩu `<tên>-demo`. `--simulator` cho phép nhân viên phát sự kiện thiết bị giả lập. `--auto-refresh` làm mới thời điểm quan sát mô phỏng để có thể tiếp tục đặt dịch vụ khi trình diễn lâu.

## Theo dõi một lượt đỗ kèm sạc

1. Mở hai phiên trình duyệt riêng biệt, chẳng hạn một cửa sổ thường và một cửa sổ riêng tư. Đăng nhập `alice` ở phiên thứ nhất và `operator` ở phiên thứ hai.
2. Trong mục **Đỗ xe** của Alice, chọn xe cá nhân `P1` và **Trạm trường đại học** (`H2`). Giữ khung giờ đề xuất, chọn **Đăng ký kèm sạc điện (phương tiện cá nhân)**, nhập mức pin mục tiêu và đặt chỗ. Mở **Xem mã QR đỗ xe** rồi sao chép trường **Mã xác nhận**. Quyền đỗ và phiên sạc được tạo trong cùng một giao dịch.
3. Đến giờ đã đặt, mở **Mô phỏng thiết bị** trong phiên của operator. Dán mã xác nhận, chọn xe, trạm và ô ghi trên phiếu rồi mô phỏng quét. Lệnh `ARRIVAL` xuất hiện ở trang **Điều hành**. Chọn **Mô phỏng ACK** cho lệnh đó để hệ thống ghi nhận xe trong ô.
4. Quay lại **Mô phỏng thiết bị** và phát sự kiện cắm sạc (`PLUG`). Khi đã đến giờ và đủ điều kiện, hệ thống phát lệnh `START`. Xác nhận lệnh để phiên chuyển sang `CHARGING`. Sau yêu cầu dừng và xác nhận `STOP`, ô vẫn còn xe. Phát lần lượt sự kiện rút cáp (`UNPLUG`) và rời bãi (`DEPARTURE`) để giải phóng ô.

Kịch bản này cũng được thực thi bằng đồng hồ kiểm thử và SQLite tạm trong `test_charging_lifecycle_and_event_replay`. Các bước qua trình duyệt nằm trong bộ kiểm thử IoT. [Kiểm thử nghiệp vụ](tests/test_iot_workflow.py) · [Kiểm thử giao diện](tests/ui_iot_workflow.py)

## Từ đặc tả đến mã chạy

Frontend HTML/CSS/JavaScript gửi lệnh HTTP đến một tiến trình Python. Bốn phân hệ dùng chung `Service` và SQLite. `BEGIN IMMEDIATE` tuần tự hóa các thay đổi cạnh tranh. Kết quả của một yêu cầu được lưu theo tài khoản và `intent_id`, cho phép gửi lại cùng yêu cầu sau khi mất kết nối. Danh tính của sự kiện thiết bị được lưu riêng để một lần quét hoặc một xác nhận gửi lặp chỉ tác động một lần. [Giao tiếp HTTP](emobility/server.py) · [Giao dịch và lưu trữ](emobility/domain.py) · [Xử lý sự kiện](emobility/iot_workflow.py)

| Phạm vi | Hành vi có thể kiểm tra | Bằng chứng thực thi |
| --- | --- | --- |
| A · Thuê xe | Hai người cùng giữ chiếc xe cuối cùng. Chỉ một yêu cầu được chấp nhận. | [Tranh chấp, hủy và gửi lại lệnh](tests/test_adversarial.py) |
| B · Đỗ xe | Mã QR gắn với quyền đỗ và chủ xe. Lượt đỗ chỉ bắt đầu sau xác nhận tiếp nhận. | [Vòng đời QR đỗ xe](tests/test_parking_qr.py) |
| C · Sạc xe | Hai phê duyệt cùng tranh tài nguyên. Khi cấp sạc thất bại, cả giao dịch đỗ kèm sạc được hoàn tác. | [Đặt chỗ, công suất và phê duyệt](tests/test_charging_requests.py) |
| D · Vận hành | Bàn giao điều chuyển từng phần giữ đúng sức chứa và vị trí xe qua lần khởi động lại. | [Điều chuyển và kịch bản giả định](tests/test_operations.py) |

## Kiểm thử

Với môi trường Python đã cài `requirements.txt`, chạy từ gốc dự án. Lệnh đầu đối chiếu SHA-256 của bốn PDF, bốn bản văn bản và prototype gốc với manifest ban đầu. Lệnh sau chạy các kiểm thử nghiệp vụ và HTTP. Trên Windows, dùng `.\.venv\Scripts\python.exe` thay cho `python` nếu chưa kích hoạt môi trường.

```sh
python scripts/verify_academic_sources.py
python -m unittest discover -s tests -v
```

Kiểm thử trình duyệt dùng Chromium để thao tác giao diện và đọc QR trực tiếp từ ảnh chụp màn hình.

```sh
python -m pip install -r requirements-test.txt
python -m playwright install chromium
python tests/ui_button_audit.py
python tests/ui_charging_reservations.py
python tests/ui_iot_workflow.py
```

Trên Linux tối giản, dùng `python -m playwright install --with-deps chromium` để cài cả thư viện hệ thống. Báo cáo mới được ghi vào `test-results/`. Các ảnh và JSON trong `tests/` là bằng chứng của những lần chạy trước. GitHub Actions cấu hình cùng các bước trên với Python 3.12, kèm kiểm tra cú pháp các tệp `web/*.js` cho pull request, push vào `main` và lần chạy thủ công. [Quy trình CI](.github/workflows/verify.yml) · [Báo cáo kiểm thử lịch sử](docs/UI_TEST_AUDIT.md)

## Triển khai và giới hạn

Blueprint Render chạy `python -m emobility.cloud_server --auto-refresh` và kiểm tra `GET /api/health`. Blueprint lấy mã từ nhánh `main` của repository chứa nó. Khi triển khai nhánh khác, đổi giá trị `branch` tương ứng. Adapter đọc hostname do Render cấp cùng năm biến mật khẩu `EMOBILITY_<TÊN_TÀI_KHOẢN>_PASSWORD` (tên tài khoản viết hoa). Gói Render Free dùng ổ đĩa tạm, dữ liệu SQLite có thể mất sau lần triển khai lại. [Blueprint](render.yaml) · [Adapter Render](emobility/cloud_server.py)

Mọi xác nhận bàn giao, kết nối cáp và trạng thái cổng sạc đều là dữ liệu mô phỏng. Ứng dụng chạy một tiến trình trên một tệp SQLite và giữ phiên đăng nhập trong bộ nhớ. [Bản xem trước HTML](deploy-demo/index.html) chạy độc lập trong trình duyệt. Dùng máy chủ Python để kiểm tra giao dịch, phân quyền và trạng thái dùng chung.

## Hồ sơ học thuật

Bài tập lớn môn Công nghệ phần mềm, Trường Đại học Bách khoa, ĐHQG TP.HCM. Nhóm thực hiện gồm **Phan Ngọc Xuân Lợi, Phan Kỳ Nhân, Phạm Gia Khang và Phạm Anh Tuấn**. Giảng viên hướng dẫn là **Trần Thị Ngọc Trâm**.

| Tài liệu | Nội dung |
| --- | --- |
| [Đề bài](docs/01_requirements/00_course_project_brief.pdf) · [Bài nộp 1](docs/01_requirements/01_assignment_1_submitted.pdf) · [Bài nộp 2](docs/01_requirements/02_assignment_2_submitted.pdf) · [Bài nộp 3](docs/01_requirements/03_assignment_3_submitted.pdf) | Bốn PDF cùng các bản văn bản có thể tìm kiếm trong thư mục [yêu cầu](docs/01_requirements/). |
| [Bảng truy vết](docs/02_design/audit_reference/UC_22_traceability_final.csv) · [Sơ đồ Mermaid](docs/02_design/mermaid_v4/) | Liên kết 22 use case với các phần đặc tả và thiết kế của nhóm. |
| [Prototype gốc](prototype/smart-emobility-clean-ui.html) · [Manifest bàn giao ban đầu](SOURCE_MANIFEST_SHA256.json) | Hiện vật tham chiếu. Manifest ghi dấu băm của gói nguồn ban đầu. |
| [Sổ tay dự án tại `462fc61`](docs/HANDBOOK.md) | Tài liệu chi tiết của nhóm về kiến trúc, quyền, API, kịch bản demo và các lần kiểm thử trước. |
