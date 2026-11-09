# Nhập dữ liệu và kiểm thử AF Booking

## Deploy bản cập nhật

Backend cần migration `0013` trước khi sử dụng bản frontend này. Render Free giữ
Start Command có `alembic upgrade head && ... uvicorn ...`; không chạy seed nếu đã
xóa biến ADMIN_USERNAME/ADMIN_PASSWORD. Sau khi Render Live, kiểm tra
`https://af-booking.onrender.com/api/v1/ready`, rồi đợi Vercel deploy cùng commit.
Nếu một provider không bật auto-deploy, dùng Manual Deploy/Redeploy commit mới nhất.

## Nhập file tháng 9/2026

1. Đăng nhập tài khoản Admin tại `https://af-booking-bice.vercel.app/`.
2. Mở **Admin → Import bookings** (`/admin/import`). Có thể chọn **Tiếng Việt**
   bằng bộ chọn ngôn ngữ; mục tương ứng là **Quản trị → Nhập booking**.
3. Chọn file văn bản gốc đã cung cấp, hoặc dán toàn bộ nội dung gồm tiêu đề:
   `Booking Number`, `Suppliers`, `Station Code`. Không cần thêm cột status.
4. Bấm **Preview import / Xem trước**. Với file 240 dòng tháng 9 đã gửi, kết quả:
   **240 dòng nguồn, 239 booking riêng biệt, 3 dòng trùng**. Nếu database chưa có
   các booking này thì 239 booking mới; nếu đã có, số mới sẽ giảm tương ứng.
5. Kiểm tra kết quả rồi bấm **Import these bookings / Nhập các booking này**.
   Chỉ thao tác này mới ghi dữ liệu vào database. Xem trước không ghi dữ liệu.
6. Mở **Summary / Tổng hợp → All bookings / Tất cả booking**, chọn kỳ `2609`.
   Bỏ bộ lọc ngày cập nhật, nhân viên và trạng thái nếu danh sách bị thiếu.

Các quy tắc đã áp dụng cho file:

- Chấp nhận `CWXXXXXXX1-PTP-2609` và `CWXXXX-LAS-2609` như booking đặc biệt.
- `CW2137352-2609`, station `CPT - JNB`, thành hai booking CPT và JNB.
- `CW2124898-2609`, station `CMN - RAK`, thành hai booking CMN và RAK.
- JFK và EWR của CW2143505 được giữ riêng; EWR đã có sẵn trong file.
- Chuẩn hóa `CW 2154749` thành `CW2154749`. Tên chỉ khác dấu, dấu câu hoặc các
  station tag cuối tên được xem là tương đương; giữ cách viết gốc đầu tiên.
- Gộp dòng ICN trùng hoàn toàn. Các dòng trùng có supplier thực sự khác bị từ chối
  để người nhập kiểm tra; không chọn một supplier tùy ý.

Booking mới có `last_status_id=NULL`, chưa có note, chưa có người cập nhật cuối,
`is_done=false`, hóa đơn chưa khai báo. Loại supplier là **Unclassified / Chưa
phân loại**, không gán tạm Hotel/Transportation. Thời điểm tạo là lúc nhập thực tế;
kỳ `2609` không có nghĩa là hệ thống tạo lịch sử giả vào tháng 9.

Nhập lại cùng file chỉ thêm booking còn thiếu. Không thay tên, loại supplier,
status, note, hóa đơn hoặc công việc của booking/thư mục đã có.

## Lưu loại supplier cho tháng sau

Dùng tài khoản Admin hoặc QC, mở thư mục nhà cung cấp của đúng **CW + station** →
**Edit supplier / Sửa nhà cung cấp** → chọn Hotel hoặc Transportation → lưu.
Sau đó dùng **New month / Tháng mới** trong thư mục. Booking của tháng mới kế thừa
supplier và loại đã lưu. Không cần phân loại lại từng tháng. Lịch tự động ngày 25 tạo kỳ đã đến hạn cho những thư mục bật sinh tháng;
không áp loại của JFK sang EWR. Xem [cấu hình lịch và CSV](monthly-bookings-vi.md).

Thông tin đã lưu tồn tại trong TiDB qua refresh, đăng xuất và deploy lại. Giao diện
vẫn cho phép Admin/QC chủ động sửa metadata; file import không ghi đè các sửa đổi đó.

## Bảng kiểm thử cho nhóm

Nên dùng các booking thử riêng như `CW9999001-SGN-2609`, `CW9999002-SGN-2609`,
`CW9999003-SGN-2609` để ghi chú thử không lẫn vào lịch sử booking nghiệp vụ thật.
Thêm ba dòng CSV/TSV tương tự file gốc với tên supplier bắt đầu bằng `[TEST]`.
Tạo ít nhất hai tài khoản Agent khác nhau và một QC bằng Admin; dùng cửa sổ hoặc
profile trình duyệt riêng cho từng tài khoản. Một tài khoản đăng nhập trên thiết bị
khác có thể làm phiên trước kết thúc theo thiết kế.

| Bước | Thao tác | Kết quả mong đợi |
| --- | --- | --- |
| 1 | Tra cứu booking tháng 9 vừa nhập | Đúng supplier/trạm/kỳ; chưa có status, note hoặc invoice |
| 2 | Nhập lại file | Số booking không tăng; dữ liệu đã bổ sung được giữ nguyên |
| 3 | Tra cứu hai mã đặc biệt | Cả hai mở được như booking thông thường |
| 4 | Tra cứu `CW2143505-2609` | Đưa ra lựa chọn JFK và EWR; không tự chọn nhầm trạm |
| 5 | Tìm CW2143505 ở chế độ thư mục | Hai thư mục riêng, điều hướng/refresh vẫn đúng trạm |
| 6 | Chọn Hotel cho một thư mục, mở tháng sau | Giữ Hotel cho cùng CW/trạm; các trạm khác không bị đổi |
| 7 | Agent A thêm Bundle cho booking thử | Một note mới, snapshot và version tăng; người cập nhật đúng |
| 8 | Chọn Rejection/Parking, bỏ trống ghi chú | Bị yêu cầu bổ sung note; nhập note hợp lệ thì lưu được |
| 9 | Chọn Done, chưa khai báo invoice | Bị yêu cầu invoice hoặc tick No invoice Number; sau khai báo mới lưu |
| 10 | Agent B mở cùng booking thử | Nhận cập nhật Live; lịch sử và trạng thái khớp với A |
| 11 | Hai người cùng sửa từ phiên bản cũ | Hiện xung đột để xem lại; không mất ghi chú đã lưu |
| 12 | Tạo reminder vài phút sau trên booking thử | Có trong Tasks, đến hạn hiện nhắc trong ứng dụng khi server đang chạy |
| 13 | Theo dõi/giao việc giữa A và B | Đúng người nhận thông báo; không lộ task riêng của người khác |
| 14 | QC/Admin xem báo cáo và xuất CSV/XLSX | Số liệu khớp hoạt động vừa thử, đúng timezone nghiệp vụ |
| 15 | Agent thử truy cập `/admin/import` và `/admin/users` | Bị chặn; Admin được phép |
| 16 | Đổi English → Tiếng Việt → refresh/đăng nhập lại | Giữ lựa chọn trên trình duyệt, nội dung chính và điều khiển lịch đổi ngôn ngữ |
| 17 | Đổi lại English | Nội dung quay lại tiếng Anh ngay; dữ liệu nghiệp vụ không bị dịch/sửa |
| 18 | Tắt mạng, soạn note trên booking thử rồi kết nối lại | Hiện trạng thái offline/draft/outbox; không tạo note trùng khi gửi lại |
| 19 | Admin xóa rồi khôi phục note thử | Timeline, snapshot và audit phản ánh đúng; invoice không bị xóa ngoài ý muốn |

Ghi kết quả mỗi bước theo mẫu: **Pass/Fail – tài khoản/role – mã booking – thao tác
– kết quả thực tế – thời điểm – thông báo lỗi**. Khi báo lỗi, không gửi password,
JWT hoặc toàn bộ biến môi trường.

Render Free có thể ngủ; reminder/push không chạy trong lúc ngủ. Trường hợp này
không chứng minh luồng nhắc nhở khi server hoạt động bị lỗi. Sau deploy frontend,
nếu PWA báo phiên bản mới thì bấm Reload trước khi kiểm tra tính năng mới.
