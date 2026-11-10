# Bật hình ảnh trong note bằng Cloudflare R2

R2 là kho lưu file trên cloud. AF Booking lưu ảnh vào kho này và lưu thông tin ảnh
trong database. Ảnh tồn tại qua các lần deploy và được đọc qua API đăng nhập của ứng
dụng. Giữ bucket ở chế độ **Private**.

## 1. Tạo kho ảnh

1. Đăng ký/đăng nhập tại <https://dash.cloudflare.com/>.
2. Mở **R2 Object Storage**, làm theo bước kích hoạt dịch vụ. Cloudflare yêu cầu
   kích hoạt billing trước khi tạo API token; kiểm tra phí trên màn hình của tài khoản.
3. Chọn **Create bucket**, đặt tên `af-booking-notes`. Chọn Standard storage và vị
   trí phù hợp với backend Singapore. Giữ Public access ở trạng thái tắt.

## 2. Tạo khóa cho đúng bucket

1. Tại R2 → Overview, chọn **Manage** bên cạnh **API Tokens**.
2. Tạo **User API token** hoặc **Account API token** nếu tài khoản hỗ trợ.
3. Chọn quyền **Object Read & Write** và chỉ định bucket `af-booking-notes`.
4. Lưu **Access Key ID**, **Secret Access Key** trong trình quản lý mật khẩu.
5. Sao chép **S3 API endpoint** của bucket. Với bucket thông thường, dạng là
   `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`. Bucket có jurisdiction riêng
   phải dùng đúng endpoint mà dashboard hiển thị.

Giữ khóa trong mục Secrets/Environment của Render. Các biến `VITE_*` được đưa vào
trình duyệt nên chỉ dùng cho cấu hình công khai.

## 3. Nhập vào backend Render

Mở đúng service API `af-booking` → **Environment**, thêm đồng thời:

| Tên biến | Giá trị |
| --- | --- |
| `S3_ENDPOINT` | S3 endpoint, chỉ gồm `https://...`, không có tên bucket |
| `S3_BUCKET` | `af-booking-notes` |
| `S3_REGION` | `auto` với R2 |
| `S3_ACCESS_KEY_ID` | Access Key ID vừa tạo |
| `S3_SECRET_ACCESS_KEY` | Secret Access Key vừa tạo |

Chọn **Save, rebuild, and deploy**. Các biến database/JWT/CORS hiện tại tiếp tục
được dùng. Migration **0014** phải được áp dụng trước khi chạy phiên bản có ticket
và ảnh; bản này có hướng dẫn release trong [workflow-release-vi.md](workflow-release-vi.md).

## 4. Kiểm tra trong ứng dụng

1. Đăng nhập bằng Agent, mở booking và lưu một note.
2. Trong **Hoạt động**, chọn **Thêm ảnh vào note này** → **Chọn hình ảnh**.
3. Chọn JPEG/PNG/WebP/GIF, tối đa 5 ảnh/note và 5 MB/ảnh.
4. Tải lại trang, mở ảnh để kiểm tra nội dung vẫn hiển thị.

User chỉ thêm ảnh vào note của chính mình; QC/Admin có thể hỗ trợ thêm ảnh. Các tài
khoản đăng nhập có quyền đọc booking xem ảnh qua API. Note đã bị xóa sẽ không cung
cấp ảnh qua API. Tải ảnh có xác thực và `no-store`, ảnh không đi vào cache offline
của PWA. Xuất backup database chứa metadata; sao lưu object R2 là bước riêng.

Khi upload lỗi, nội dung note đã lưu vẫn còn. Gửi lại cùng ảnh cho cùng note sẽ dùng
lại bản đã có, tránh tạo bản đính kèm trùng. Một PUT thành công nhưng giao dịch DB bị
hủy có thể để lại object riêng tư chưa có metadata; cần rà object không được tham
chiếu khi bảo trì kho, giữ các object đang được bảng `attachments` sử dụng.

Tài liệu Cloudflare: [Bắt đầu](https://developers.cloudflare.com/r2/get-started/),
[API token](https://developers.cloudflare.com/r2/api/tokens/),
[Giá R2](https://developers.cloudflare.com/r2/pricing/).
