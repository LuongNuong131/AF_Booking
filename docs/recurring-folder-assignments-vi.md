# Phân công folder cố định hằng tháng

Workspace có thêm **Task của tôi**, độc lập với My bookings (người cập nhật gần nhất),
reminder cá nhân và ticket gửi QC. Người phụ trách được lưu tại folder CW + station;
booking các tháng dùng chung folder nên không phải phân công lại khi đổi kỳ YYMM.
Phân công giúp tìm công việc, không giới hạn quyền xem hay xử lý booking của người khác.

## Cài đặt và nhập file

1. Triển khai backend/frontend cùng phiên bản; chạy `alembic upgrade head` từ `backend`
   bằng cấu hình database hiện có. Migration `0017` bổ sung metadata, không tạo tài khoản.
2. Admin mở **Admin → Data import** (`/admin/import`), phần **Nhập phân công cố định**.
3. Chọn `Booking_Merged_Agents.xlsx`. Mở mapping để kiểm tra username đang hoạt động.
   Mapping đã xác nhận: `Tran → HuyenTran`, `Thang → XuanThang`.
   Kha/Phuong có thể là user QC (`NguyenKha`, `ThuPhuong`) và vẫn nhận folder.
4. Bấm **Xem trước**, xem toàn bộ các dòng và các dòng cần kiểm tra, rồi bấm nhập.
5. Agent mở **Workspace → Task của tôi**. Mặc định hiển thị folder của mình;
   có thể chọn tất cả, chưa phân công, cần kiểm tra, region hoặc người phụ trách.

Không cần nhập lại file hằng tháng. Cơ chế tạo tháng có sẵn tiếp tục sử dụng cùng folder
và giữ người phụ trách. Không tạo note, trạng thái Done, invoice hay người xử lý giả.
Nếu CW gốc thay đổi (không chỉ YYMM), đó là folder mới và cần nhập/gán cho folder mới.

## Quy tắc nhập

- Đọc dữ liệu sheet **Merged**, không chạy công thức hoặc làm theo nội dung ghi chú.
  File XLSX tối đa 500 KB, 2000 dòng; giới hạn kích thước giải nén.
- Chuẩn hóa số booking; loại dòng trùng tương đương. Hai dòng CW không có station
  nhưng có danh sách station rõ ràng như `CPT - JNB` được tách thành hai booking.
  Trùng booking mà khác người phụ trách, supplier, region hoặc loại sẽ bị từ chối.
- File được cung cấp có 240 dòng, gộp 3 dòng trùng, tách 2 dòng hai station: 239 booking,
  gồm 124 Hotel, 92 GT, 23 chưa phân loại/loại gộp. Không suy đoán HOTEL/GT thành Hotel.
- `Cần check` chưa tự gán dù cột Agent có gợi ý: 6 folder chờ xác nhận. Giữ đầy đủ
  thông tin Country, City, AF Zone, Type gốc, payment terms, level, legal invoice, ghi chú.
  Các giá trị địa lý được giữ từ file, không tự hiệu chỉnh dữ liệu có vẻ lệch.
- Nếu username chưa có/không hoạt động, nhập booking nhưng để chưa phân công và đánh dấu.
- Nhập lại giữ phân công đã lưu/chỉnh, loại đã phân loại, lịch sử và booking hiện có.
  Không khôi phục ngầm dữ liệu trong thùng rác.

## Chỉnh sửa

Admin/QC sửa người phụ trách, region, ghi chú cần kiểm tra và phân loại. Agent sửa
phân loại folder; mọi user đang hoạt động tiếp tục sửa phân loại từng booking như trước.
Phân loại folder là mặc định cho mọi tháng chưa có override và các tháng mới.
Booking đã được phân loại riêng giữ override. Chỉnh metadata không đổi last agent,
trạng thái, note, version booking hay đồng hồ stale. Lưu folder dùng optimistic version;
nếu có người sửa đồng thời, phải mở lại bản mới. Tất cả thay đổi ghi audit.

## API

- `GET /api/v1/folder-assignments?scope=mine|all|unassigned|review&agent_id=&region=&q=&page=&size=`
  trả `Page<FolderAssignmentItem>`, mặc định 20 folder; phân trang và lọc ở server.
- `GET /api/v1/folder-assignments/options`: user đang hoạt động, region và mapping mặc định.
- `PATCH /api/v1/folder-assignments/{group_id}`: `expected_version`, các trường cần sửa.
- `POST /api/v1/admin/folder-assignments/import`: `workbook` base64, `agent_map`, `apply`.
  Preview/apply đều kiểm tra lại tài khoản và dữ liệu; apply là một transaction.

Dữ liệu Excel thực tế không được đưa vào Git/public assets. Admin upload trực tiếp vào
ứng dụng sau khi triển khai. Test workbook thực tế chỉ dùng database tạm, không ghi production.

## Kiểm tra

```sh
cd backend
.venv/bin/python -m pytest tests/test_folder_assignments.py -q
ASSIGNMENT_CHECK_FILE=/absolute/path/Booking_Merged_Agents.xlsx \
.venv/bin/python tests/run_schema_checks.py --engine mysql --suite folder-assignments --report /tmp/assignments-mysql.xml
# Đổi mysql thành tidb để kiểm tra engine production.
BOOKING_CHROMIUM_PATH=/usr/bin/chromium \
.venv/bin/python tests/run_schema_checks.py --engine mysql --suite assignment-browser --report /tmp/assignments-browser.xml
```

Suite `folder-assignments` kiểm tra preview không ghi, nhập/gộp, phân công QC, chưa xác định, nhập lại,
đổi người xử lý, rollover tháng, classification, optimistic conflict, quyền. Suite `assignment-browser` kiểm tra
upload → folder → tháng. Browser kiểm tra 320/375/768/1440px trên dữ liệu/tài khoản tạm.

Kết quả ngày 11/11/2026: 237 backend unit test, 280 frontend test; 5 case nghiệp vụ
và migration/schema suite trên mỗi engine MySQL/TiDB đều qua. Chromium với API thật
đã qua luồng import/phân loại/mở tháng/truy cập chung ở cả 4 kích thước trên.
Xem [verification record](quality/recurring-assignments-verification.json).
