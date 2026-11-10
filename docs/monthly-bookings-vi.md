# CSV, lịch tháng và triển khai bản cập nhật

## Triển khai

Commit này cần migration **0013**. Trên Render Free, giữ Start Command đã cấu hình
chạy `alembic upgrade head` trước Uvicorn; không xóa database hoặc chạy lại seed.
Đợi backend Live và `https://af-booking.onrender.com/api/v1/ready` trả kết nối tốt,
sau đó đợi Vercel deploy cùng commit. Nếu auto-deploy tắt, Manual Deploy / Redeploy
commit mới nhất. Frontend vẫn dùng `VITE_API_URL=https://af-booking.onrender.com/api/v1`.

## File nhập booking

Tải mẫu từ trang **Admin → Import bookings → Download CSV template**,
hoặc `https://af-booking-bice.vercel.app/booking-template.csv`.
CSV UTF-8, phân cách dấu phẩy, tối đa 2.000 dòng nguồn / 500.000 ký tự mỗi lượt.
Có thể dùng TSV. Ba cột đầu bắt buộc; hai cột sau tùy chọn:

```csv
Booking Number,Suppliers,Station Code,Supplier Type,Recurring
CW9999001-SGN-2610,"Example Hotel, Saigon",SGN,hotel,true
CW9999002-HAN-2610,Example Transport,HAN,transportation,true
CWXXXX-LAS-2610,Example Supplier,LAS,,false
```

- `Booking Number`: CW + station + kỳ YYMM; `2610` là tháng 10/2026. Mã đặc biệt
  chứa X được chấp nhận. Mỗi CW/station là một thư mục độc lập.
- `Suppliers`: tên nhà cung cấp, 3–255 ký tự. Tên chứa dấu phẩy phải đặt trong
  dấu ngoặc kép. Trong Excel chọn **CSV UTF-8 (Comma delimited)**.
- `Station Code`: ba chữ cái. Danh sách `CPT - JNB` được tách thành hai booking.
- `Supplier Type`: để trống (Unclassified), `hotel`, `transportation`,
  hoặc `unclassified`. Agent, QC và Admin đều có thể dùng **Sửa phân loại** trong workspace booking hoặc folder để chọn Hotel/Transportation sau.
- `Recurring`: `true` (mặc định nếu thiếu cột/để trống) để sinh kỳ sau;
  `false` cho booking một lần. Chỉ áp dụng lúc tạo thư mục mới.

Không cần cột status, note hoặc invoice. Nhập lại chỉ thêm booking còn thiếu;
không ghi đè dữ liệu hay phân loại đã được nhân viên cập nhật.

## Cách nhập an toàn

1. Đăng nhập Admin, mở `/admin/import`, chọn file.
2. Mặc định giữ chế độ báo lỗi nếu station trong mã và trong cột không khớp.
   Nếu đã kiểm tra nguồn, có thể chọn ưu tiên **Station Code** hoặc **Booking Number**.
3. Tùy chọn điền supplier thiếu chỉ hoạt động khi cùng CW trong file có đúng một
   nhà cung cấp tương đương. Không đoán theo CW khác hoặc tạo tên giả.
4. Bấm **Preview import / Xem trước**, mở danh sách điều chỉnh và kiểm tra từng dòng.
   Xem trước không lưu vào database.
5. Khi đã đúng, bấm **Import these bookings / Nhập các booking này** một lần.
   Không phải nhập từng mã thủ công.
6. Mở Summary, chọn kỳ cần xem và xóa bộ lọc ngày/status/người phụ trách nếu thiếu kết quả.

### File bookings_clean.csv đã gửi

File có UTF-8 BOM và đúng ba cột, **1.425 dòng**, thuộc các kỳ `2604`–`2609`.
Bản cũ giới hạn 1.000 dòng nên không nhập được. File còn một số vấn đề nguồn:

| Dòng CSV (gồm tiêu đề) | Vấn đề cần duyệt |
| --- | --- |
| 302 | Mã ghi JFK, cột station ghi EWR |
| 476 | Mã ghi CDG, cột station ghi YUL |
| 478 | Mã ghi CDG, cột station ghi YVR |
| 632 | Mã ghi MEX, cột station ghi NLU |
| 1191 | Mã ghi FRA, cột station ghi BER |
| 488–489 | Thiếu supplier của CW2161901; dòng MXP còn thiếu station |

Trong file có một dòng đủ thông tin của CW2161901 ở dòng 242. Chỉ dùng tên ở
dòng này để điền hai dòng trống sau khi người quản lý xác nhận cùng nhà cung cấp.

**Phương án đề xuất, chưa phải dữ liệu đã nhập:** ưu tiên Station Code, điền supplier
thiếu theo cùng CW, tách các danh sách station. Kết quả kiểm thử là **1.400 booking
riêng biệt**, **35 bản trùng sau khi tách**, **14 điều chỉnh được liệt kê để xem trước**.
Số booking mới thực tế phụ thuộc database đã có những mã nào. Không cộng đơn giản
1.400 + 35 với 1.425 vì có dòng mở rộng thành nhiều station. File nghiệp vụ đầy đủ
không được đưa vào GitHub. Các kiểm thử nhập chạy trên TiDB tạm, không phải database thật.

## Quy tắc sinh tháng

Múi giờ mặc định `Asia/Ho_Chi_Minh`, ngày chạy mặc định **25**:

| Thời điểm | Kỳ đã đến hạn | Tháng xử lý |
| --- | --- | --- |
| 01–24/11/2026 | 2610 | tháng 11 xử lý tháng 10 |
| Từ 25/11/2026 | 2611 | chuẩn bị cho tháng 12 |
| Từ 25/12/2026 | 2612 | chuẩn bị cho tháng 01/2027 |

Hệ thống giữ CW, station, tên và loại supplier của thư mục; tạo booking kỳ mới với
status/note/invoice trống. Không sao chép kết quả xử lý kỳ trước. Chạy lại không tạo
trùng hoặc xóa booking hiện có. Khi bật tính năng trên dữ liệu cũ, hệ thống bù các kỳ
còn thiếu sau kỳ mới nhất đã đến hạn của mỗi thư mục đến kỳ cần xử lý; ví dụ nhập kỳ tháng 9
vào đầu tháng 11 thì có thể tạo thêm kỳ tháng 10. Các khoảng trống trong lịch sử trước kỳ mới nhất không bị tự lấp. Lịch sử cũ vẫn giữ nguyên.

Admin/QC có thể mở thư mục → **Edit supplier** → bỏ chọn **Generate monthly bookings**
cho nhà cung cấp ngừng hoạt động/booking một lần. Nếu bật lại, các kỳ thiếu sẽ được
bù. Có thể dùng `Recurring=false` từ lần nhập đầu.

Backend kiểm tra mỗi 5 phút và khi khởi động. Mỗi lượt xử lý tối đa 100 thư mục,
12 kỳ/thư mục, có checkpoint để tiếp tục ở lượt sau. Nút **Generate missing due bookings**
trên trang Import chạy một lượt; xem số thư mục chờ để biết còn cần lượt tiếp theo.

## Render Free: cấu hình gọi lịch từ GitHub Actions

Render Free có thể ngủ; bộ lập lịch trong backend chỉ chạy khi service thức.
Workflow được thêm sẵn trong repo để gọi backend theo giờ Việt Nam kể cả lúc service
đang ngủ. Cần cấu hình các giá trị sau một lần; code không tự tạo secret trong tài khoản:

1. Render → service AF Booking → **Environment → Add Environment Variable**:
   - `MONTHLY_BOOKING_ENABLED=true`
   - `MONTHLY_BOOKING_DAY=25`
   - `BUSINESS_TIMEZONE=Asia/Ho_Chi_Minh` (giữ nếu đã có)
   - `MONTHLY_BOOKING_TOKEN`: tạo chuỗi ngẫu nhiên ít nhất 32 ký tự bằng **Generate**.
     Lưu lại riêng để dùng đúng cùng chuỗi ở bước tiếp theo. Đây là token lịch,
     không phải mật khẩu database hoặc mật khẩu Admin.
2. Chọn **Save, rebuild, and deploy**, đợi Live.
3. GitHub repo → **Settings → Secrets and variables → Actions → Secrets → New
   repository secret**: tên `MONTHLY_BOOKING_TOKEN`, giá trị giống hệt Render.
4. Cùng trang → **Variables → New repository variable**:
   tên `AF_BOOKING_API_URL`, giá trị `https://af-booking.onrender.com`
   (không thêm `/api/v1`).
5. GitHub → **Actions → Generate monthly bookings → Run workflow → main → Run**.
   Nếu workflow chưa bật, chọn Enable workflow. Đợi kết quả màu xanh; log báo kỳ
   và số tạo, không in token. Chạy lại không tạo bản trùng.
6. Trang Admin Import → Refresh: kiểm tra kỳ đến hạn, số thư mục đang bật và số chờ.

Workflow lên lịch 17:00 UTC ngày 24, tương ứng 00:00 ngày 25 ở Việt Nam. GitHub có
thể chạy trễ; nếu bị bỏ lỡ, backend sẽ bù khi thức hoặc có thể Run workflow lại.
Repo public không hoạt động lâu có thể bị GitHub tắt scheduled workflow, cần bật lại.
Lịch dùng múi giờ Việt Nam cố định; nếu đổi timezone/ngày backend thì phải sửa cron
workflow tương ứng. Khi muốn tạm dừng toàn bộ, đặt `MONTHLY_BOOKING_ENABLED=false`.

## Kiểm tra sau triển khai

- Logo AF ở trang đăng nhập, sidebar, thanh mobile và favicon; English là ngôn ngữ
  mặc định, có Tiếng Việt, sáng/tối.
- Kiểm tra trên điện thoại: mở menu, Summary, trang Import và dialog tạo user.
  Bảng booking hiển thị thẻ có nhãn; bảng quản trị có vùng cuộn ngang riêng.
- Xem trước file full trước khi nhập. Sau nhập thử lại Preview: mã đã có không được
  tính là mới. Đọc một booking kỳ cũ để chắc status/note vẫn nguyên.
- Sửa phân loại supplier của đúng CW/station; chạy sinh kỳ đã đến hạn; kiểm tra kỳ mới
  kế thừa phân loại và chưa có trạng thái. Chạy lần nữa không tăng số bản ghi.
