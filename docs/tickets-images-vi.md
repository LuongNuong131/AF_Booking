# Ticket có tiêu đề, ảnh và tổng hợp cho QC

## Agent

Trong booking, mở **Ticket gửi QC**:

1. Chọn gợi ý **Lỗi contract** hoặc **Lỗi hệ thống — Cannot send rejection letters**.
2. Tiêu đề tự tạo theo gợi ý và mã booking chuẩn, ví dụ `AF_Non-standard process_Contract issue - CW2074043-BUD-2610`.
3. Nhập nội dung tiếng Anh (bắt buộc, tối đa 2.000 ký tự).
4. Mở **Hình ảnh** để chọn nhiều ảnh, xem trước hoặc bỏ từng ảnh trước khi tạo ticket.

Mỗi ticket/note nhận tối đa 5 ảnh, mỗi ảnh tối đa 5 MiB, định dạng JPEG/PNG/WebP/GIF. Ảnh dùng cùng kho S3/R2 riêng tư như ảnh note; máy chủ kiểm tra định dạng và quyền truy cập. Agent chỉ xem được ticket và ảnh ticket do mình tạo; QC/Admin xem được toàn bộ ticket.

Nếu ticket đã tạo nhưng tải ảnh lỗi, form giữ ticket và ảnh chưa gửi để **Thử lại**. Không tạo thêm ticket khi thử lại. Giữ trang mở đến khi tải ảnh hoàn tất.

### Hỗ trợ dịch không bắt buộc

Mở **Hỗ trợ dịch Việt → Anh**, nhập mô tả tiếng Việt:

- **Mở Google Dịch** dùng được ngay, không cần API key. Copy bản tiếng Anh về ô kiểm tra bản dịch rồi chọn **Dùng nội dung tiếng Anh này**.
- Để dịch trực tiếp trong form, quản trị viên bật Cloud Translation API trên Google Cloud và thêm secret `GOOGLE_TRANSLATE_API_KEY` ở backend, rồi khởi động lại dịch vụ. API key ở máy chủ, không nằm trong bundle frontend. Dịch vụ có thể tính phí theo tài khoản Google Cloud.
- Nội dung chỉ gửi tới Google khi người dùng nhấn dịch hoặc mở liên kết Google Dịch. Kiểm tra bản dịch trước khi áp dụng; không tự ghi đè nội dung ticket.

Kiểm tra ngôn ngữ chặn nội dung rỗng, chỉ gồm số/ký hiệu và các ký tự đặc trưng tiếng Việt, kể cả Unicode tổ hợp. Đây là kiểm tra hỗ trợ, không phải bộ nhận diện ngôn ngữ đầy đủ; không phát hiện đáng tin cậy tiếng Việt không dấu hoặc mọi ngôn ngữ khác.

## QC

Mục **Ticket** giữ bộ lọc trạng thái/ngày/người tạo/booking, mặc định là hàng chờ chưa xử lý của mọi ngày. Bấm tiêu đề hoặc **Mở ticket** để xem tiêu đề, nội dung đầy đủ, ảnh, người tạo và kết quả xử lý. Có nút copy tiêu đề, nội dung hoặc cả hai. Nếu trình duyệt từ chối clipboard, chọn và copy thủ công từ ô dự phòng. Ảnh có thể mở hoặc tải riêng.

Để tổng hợp lỗi không gửi được rejection letter:

1. Lọc theo ngày nếu cần, tích các ticket **Cannot send rejection letters**; lựa chọn được giữ khi chuyển trang (tối đa 100 ticket).
2. Chọn **Gộp để copy**. Ticket loại contract không có ô chọn gộp và backend cũng từ chối gộp khác loại.
3. Tiêu đề tổng hợp là `AF_System Issues_Cannot send rejection letters`. Nội dung đúng mẫu:

```text
Please check these invoice which cannot send the rejection letter on TIM Tool - we had to send manually the rejection letter via Billing Email section, and force it from the Parking tab to Rejection tab

CW2114762-DUB-2610
CW2129797-LYS-2610
CW2132474-TNR-2610
```

Mỗi booking xuất hiện một lần, theo thứ tự chọn. Ảnh của tất cả ticket được hiển thị cùng bản tổng hợp. Đây là bản tổng hợp để copy; giữ nguyên ticket gốc và trạng thái xử lý. QC đánh dấu đã xử lý trong chi tiết từng ticket.

## Chọn ảnh khi soạn note

Trong form thêm note, mở **Hình ảnh**, chọn ảnh trước rồi bấm lưu note như bình thường. Không cần tạo note trước để chọn ảnh nữa. Cách thêm ảnh vào note đã lưu vẫn dùng được.

Khi bấm lưu, ảnh được lưu vào IndexedDB của trình duyệt trước khi form được xóa. Outbox gửi note rồi tải ảnh lên note đó. Nếu mạng/kho ảnh lỗi, outbox giữ ảnh và kết quả note đã lưu; thử lại hoặc tải lại trang tiếp tục tải ảnh mà không gửi lại note. Nếu muốn bỏ ảnh còn lỗi, chọn **Giữ note đã lưu và bỏ ảnh chưa gửi** trong outbox. Chờ outbox hoàn tất trước khi xóa dữ liệu trang web. Ảnh chỉ mới chọn nhưng chưa bấm lưu chưa được lưu thành bản nháp.

## Phát hành

Chạy migration trước khi khởi động backend mới:

```sh
cd backend
alembic upgrade head
```

Migration `0016` thêm `issue_type`, `title` vào `booking_work_tasks`, và `work_task_id` vào `attachments`; `note_id` cho phép null để lưu ảnh ticket. Dữ liệu ticket cũ không bị đổi, vẫn đọc được và có tiêu đề dự phòng bằng mã booking. Client cũ vẫn tạo được ticket không phân loại, không thể gộp nhầm với loại lỗi mới.

Render Blueprint hiện có `preDeployCommand: alembic upgrade head`; kiểm tra dịch vụ thực tế đang dùng cấu hình này. Ảnh tiếp tục cần các secret S3/R2 đã có trong [hướng dẫn ảnh note](note-images-vi.md). Khi xóa vĩnh viễn booking, ảnh note và ảnh ticket đều được đưa vào hàng chờ dọn kho ảnh. Không downgrade `0016` khi còn ảnh ticket vì schema cũ không biểu diễn được dữ liệu này.
