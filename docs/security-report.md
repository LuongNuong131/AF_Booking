# Báo cáo bảo mật — Prompt 9

Ngày rà soát: **04/11/2026**. Phạm vi: mã nguồn frontend/backend qua Prompt 8F,
được gia cố theo Prompt 9; kiểm thử trên database MySQL/TiDB cô lập có TLS và
Chromium thật. Bảng ghi kết quả trong mã nguồn; cấu hình tên miền và xác minh dịch
vụ đã deploy thực hiện sau khi tạo Vercel, Render, TiDB Cloud.

| Hạng mục | Kết quả | File liên quan |
| --- | --- | --- |
| Mật khẩu và Argon2id | **Đã sửa:** mật khẩu mới/tạm 10–128 ký tự, khác username sau NFKC/casefold; hash 64 MiB, 3 lượt, parallelism 2; giới hạn luồng hash. CLI seed dùng Argon2id 64 MiB/3 lượt/parallelism 4. Không có tài khoản/mật khẩu mặc định. | `backend/app/core/security.py`, `app/schemas/auth.py`, `app/services/admin.py`, `app/scripts/seed.py` |
| Đổi mật khẩu lần đầu | **Đã sửa:** migration mới 0008; seed/create/reset đặt cờ; API chỉ cho me/logout/change-password, WebSocket từ chối phiên bị giới hạn; UI riêng; đổi xong thu hồi SID và đăng nhập lại. | `backend/alembic/versions/0008_password_rotation.py`, `app/core/deps.py`, `app/services/auth.py`, `frontend/src/views/RequiredPasswordView.vue`, `src/router/index.ts` |
| JWT và khóa ký | **Đạt / đã sửa:** chỉ HS256; bắt buộc exp/sid/sub/role/iat/iss/aud, kiểm tra chữ ký/hết hạn/UUID; production từ chối khóa thiếu, ngắn, toàn khoảng trắng hoặc mẫu mặc định. Hỗ trợ tên JWT_SECRET và JWT_SECRET_KEY. | `backend/app/core/config.py`, `app/core/security.py`, `tests/test_security.py`, `tests/test_hardening.py` |
| Chống dò tài khoản | **Đã sửa:** hai bộ đếm IP và username độc lập, khóa 5 phút sau 5 lần sai; tuần tự hóa khi đồng thời, chặn IP trước DB; thông báo sai thông tin giống nhau cho tên không tồn tại/sai mật khẩu/user khóa. | `backend/app/services/login_limiter.py`, `app/services/auth.py`, `tests/test_auth_database.py` |
| Phân quyền Admin/QC | **Đạt:** dependency dùng role hiện tại; agent bị chặn; admin không tự khóa/hạ quyền; Supplier chỉ admin/qc sửa và có audit. | `backend/app/core/deps.py`, `app/services/admin.py`, `app/api/v1/bookings.py`, `tests/test_admin_database.py`, `tests/test_folder_database.py` |
| IDOR dữ liệu cá nhân | **Đạt:** task/thông báo lọc theo chủ; assignment chỉ người giao/nhận; push endpoint không chuyển quyền sở hữu; invoice chỉ người thêm/qc/admin xóa. Lỗi ID không thuộc quyền không tiết lộ dữ liệu. | `backend/app/services/tasks.py`, `app/api/v1/notifications.py`, `app/services/collaboration.py`, `app/services/push.py`, `app/services/invoice_service.py`, `tests/test_hardening_database.py` |
| Giới hạn đầu vào | **Đã sửa:** body tối đa 1 MiB trước JSON, kể cả chunked/Content-Length giả; parser từ chối chuỗi >100 trước chuẩn hóa; path ID/key có cận; note tối đa 5000 ký tự; schema giới hạn chuỗi, loại ký tự điều khiển. | `backend/app/core/http_security.py`, `app/core/bounds.py`, `app/schemas/contracts.py`, `app/utils/booking_key.py`, `app/utils/text.py` |
| SQL injection | **Đạt / đã sửa:** ORM/tham số ràng buộc, kể cả SET SESSION; không ghép giá trị vào SQL. Test AST bảo vệ điểm gọi text/execute/executemany; chuỗi SQL độc hại được coi là văn bản hoặc khóa sai. | `backend/app/core/db.py`, `tests/test_hardening.py`, `tests/test_hardening_database.py` |
| CORS / WebSocket | **Đã sửa:** Origin phải khớp danh sách chính xác, không wildcard; WS thiếu/sai Origin đóng 4403, sai token 4401; giới hạn 4096 byte và 20 message/giây; đóng client chậm theo timeout. | `backend/app/core/config.py`, `app/api/v1/realtime.py`, `app/services/ws_manager.py`, `tests/test_hardening_database.py`, `tests/test_realtime_database.py` |
| Header và cache | **Đã sửa:** nosniff, frame DENY, Referrer-Policy; no-store cho dữ liệu API cá nhân, cả lỗi. Catalogue status/station không chứa dữ liệu cá nhân vẫn giữ private ETag. | `backend/app/core/http_security.py`, `frontend/vercel.json`, `tests/test_hardening.py` |
| Timeout / quá tải | **Đạt / đã sửa:** mọi HTTP route chịu deadline chung, lookup/save/export có ngân sách riêng; hủy truy vấn, loại kết nối bị hủy; 503/504 không trả SQL/stack; Retry-After là số giây ASCII. | `backend/app/core/timeouts.py`, `app/core/unit_of_work.py`, `app/core/errors.py`, `app/core/http_security.py`, `tests/test_booking_database.py` |
| Log và lỗi | **Đã sửa:** log route template, không đường dẫn thô/query token/nội dung note/mật khẩu; lọc token WS; validation không echo input; top slow query chỉ fingerprint, không tham số. | `backend/app/core/request_context.py`, `app/core/errors.py`, `app/services/telemetry.py`, `tests/test_request_context.py`, `tests/test_operations_database.py` |
| Giới hạn tính năng 8B–8F | **Đạt / đã sửa:** warm theo IP; lookup/search/note/invoice tìm kiếm có giới hạn; users/lookup chỉ id/full_name của user hoạt động; invoice tối đa 50 phần tử/yêu cầu; quyền sửa/xóa được kiểm tra trong transaction. | `backend/app/api/v1/health.py`, `app/api/v1/bookings.py`, `app/api/v1/operations.py`, `app/services/invoice_service.py`, `tests/test_invoices_database.py` |
| CSV / Excel injection | **Đạt:** escape giá trị công thức ở daily/invoice/nhiều sheet; test `=1+1` trở thành `'=1+1`; Booking xuất theo display_key mặc định. | `backend/app/services/exports.py`, `app/services/invoice_exports.py`, `tests/test_export_rules.py`, `tests/test_admin_database.py`, `tests/test_invoices_database.py` |
| PWA / Web Push | **Đạt:** worker chỉ cache tài nguyên tĩnh, không API; push tối thiểu không note, bỏ qua user online, kiểm tra chủ, dọn subscription 404/410; endpoint HTTPS theo allowlist nhà cung cấp, không theo redirect. | `frontend/src/pwa/service-worker.js`, `frontend/pwa-build.ts`, `backend/app/services/push.py`, `tests/test_operations_database.py`, `frontend/e2e/pwa.mjs` |
| XSS / v-html | **Đã sửa:** ESLint vue/no-v-html mức error áp dụng mọi Vue component; probe âm chứng minh bị chặn. Note, invoice, tên người dùng hiển thị text; highlight dùng mark. Không log token/dữ liệu nhạy cảm ra console. | `frontend/eslint.config.js`, `scripts/check-security.mjs`, `src/components/NoteHighlight.vue`, `src/components/InvoicePanel.vue`, `e2e/operations.mjs` |
| CSP | **Đã sửa:** default/script self, connect đúng API/WSS origin, frame-ancestors none; script theme đã ra file ngoài. Script cấu hình + guard từ chối Vercel build khi origin lệch. **Ghi chú:** thay ví dụ api.example.com bằng URL Render thật trước deploy. | `frontend/vercel.json`, `src/config/csp.ts`, `scripts/configure-csp.mjs`, `vite.config.ts`, `src/theme-init.ts`, `e2e/pwa.mjs` |
| Token / nhiều tab | **Đã sửa:** localStorage theo yêu cầu; tự đăng xuất theo exp, storage event đồng bộ; xóa token/store khi logout/đá phiên; phản hồi cũ không xóa token mới. Web Locks/BroadcastChannel chia sẻ một WS, chuyển tab giữ kết nối khi đóng tab cũ. | `frontend/src/stores/auth.ts`, `src/composables/useSharedRealtime.ts`, `src/runtime/application.ts`, `src/stores/hardening.test.ts`, `e2e/security.mjs` |
| Phụ thuộc | **Đã sửa:** ghim phiên bản trực tiếp, Python lock có hash và npm lock; cập nhật test tooling/transitive glob/minimatch/js-beautify; pip-audit/npm audit toàn bộ runtime + dev không còn cảnh báo đã biết trong lần quét này. CI chạy lại audit/lint/test. | `backend/requirements*.in`, `backend/requirements*.txt`, `frontend/package*.json`, `.github/workflows/ci.yml`, `docs/security/` |

Đường dẫn `app/`, `tests/` trong các hàng backend tương đối với `backend/`;
`src/`, `scripts/`, `e2e/` trong các hàng frontend tương đối với `frontend/`.

## Cấu hình khi deploy

Chạy `alembic upgrade head` lên **0011** trước khi khởi động phiên bản này. Migration mới
thêm index cho notification feed và danh sách task đã hoàn tất. Cờ mới
đánh dấu account chưa từng login trong dữ liệu cũ; các tài khoản đã dùng trước đó
không bị đặt lại mật khẩu. Seed chạy lại giữ nguyên mật khẩu và cờ đã hoàn tất.
Admin reset luôn buộc đổi và thu hồi phiên cũ. Không sửa migration cũ.

Khi Render cấp URL, chạy từ frontend:

```sh
VITE_API_URL=https://YOUR-API.onrender.com/api/v1 npm run configure:csp
```

Commit `frontend/vercel.json` đã cập nhật **trước** lần deploy Vercel, rồi đặt cùng
VITE_API_URL/VITE_WS_URL ở Vercel. Render CORS_ORIGINS chứa chính xác origin Vercel;
WS dùng cùng allowlist. VERCEL=1 build từ chối origin CSP lệch môi trường. CSP chỉ
nới `style-src 'unsafe-inline'` cho Element Plus và style tính toán của virtual list;
không nới script inline/eval. Domain API/WSS không dùng wildcard. Xem [deploy.md](deploy.md).

Giữ một backend instance/worker vì limiter, session cache, locks và telemetry ở
bộ nhớ. Chỉ tin proxy được khai báo đúng FORWARDED_ALLOW_IPS ở deployment thực tế;
không đọc tùy ý X-Forwarded-For. Server ngủ không phát push cho tới lúc thức lại.

## Lưu token và phương án cookie

Mặc định localStorage giúp các tab cùng sử dụng một phiên; cùng origin có XSS thì
script vẫn có thể đọc token. CSP, render text, cấm v-html và kiểm tra dependency giảm
nguy cơ, không biến localStorage thành kho bí mật. Logout/expiry/force logout xóa
token và dữ liệu **đang hiển thị trong bộ nhớ**, hủy request, task/notices/caches.
Draft/outbox bền vững vẫn phân vùng theo user để giữ công việc chưa gửi; chúng không
hiển thị hay truyền đi khi đăng xuất. Xóa site data khi dùng máy chung và cần bỏ
cả bản nháp. Token không được truyền trong BroadcastChannel hoặc log.

Phương án khác là cookie `HttpOnly; Secure; SameSite=None` do FE/BE khác site,
Axios credentials + CORS origin chính xác/allow-credentials; cần thêm phòng CSRF
(token hoặc kiểm tra Origin cho mutation) và cân nhắc hạn chế cookie bên thứ ba.
Đây là lựa chọn kiến trúc được ghi nhận, chưa chuyển cơ chế auth của bản hiện tại.
Trình duyệt thiếu Web Locks/BroadcastChannel dùng fallback một tab có WS hoạt động;
các tab vẫn dùng chung token và REST.

## Bằng chứng và chạy lại

Kết quả kiểm thử cuối được ghi ở [testing.md](testing.md#prompt-9-security-verification).
Audit JSON và hash lockfile ở [security/](security/). Các cảnh báo deprecation của
FastAPI ORJSONResponse và Starlette TestClient được ghi trong log test; đây không
phải finding của audit. Không dùng ignore-CVE hoặc tắt kiểm tra TLS để đạt kết quả.

```sh
cd backend
.venv/bin/ruff check . ../scripts
.venv/bin/ruff format --check .
.venv/bin/python ../scripts/generate_contract_types.py --check
.venv/bin/python -m pytest -q
.venv/bin/pip-audit --disable-pip --no-deps -r requirements-dev.txt
.venv/bin/python tests/run_schema_checks.py --engine mysql --suite security --report /tmp/security-mysql.xml
.venv/bin/python tests/run_schema_checks.py --engine tidb --suite security --report /tmp/security-tidb.xml
cd ../frontend
npm ci
npm run lint
npm run test:security
npm test
npm audit --audit-level=low
VITE_API_URL=https://api.example.com/api/v1 VERCEL=1 npm run build
```

Bộ integration hiện có bổ sung kiểm tra ACL/IDOR, khóa tài khoản, assignment/push,
invoice/xuất file, lỗi 503/504, hủy truy vấn và WS client chậm. Runner chỉ tạo database
cô lập có tên kiểm thử, dọn container sau khi xong; không có endpoint test trong
production. Chromium kiểm tra thật 12 kịch bản, gồm CSP chặn inline script, PWA không
cache API, đổi mật khẩu ban đầu, chia sẻ socket và logout giữa các tab.

Kết quả không khẳng định hệ thống không thể có lỗ hổng trong tương lai. Chưa dùng
credential/provider thật, chưa xác minh ingress/header sau deploy hay chạy kiểm thử
xâm nhập trên hạ tầng Vercel/Render/TiDB Cloud; đó là bước cấu hình/kiểm tra khi có
URL theo yêu cầu triển khai sau của chủ dự án.

Prompt 10 adds a current dependency scan with zero known findings at
[quality/audits/metadata.json](quality/audits/metadata.json). Its complete functional
regressions, 13-script browser batch and coverage are recorded in
[testing.md](testing.md). Load latency targets remain separately reported in
[performance/load-results.md](performance/load-results.md); they are not labeled
as passed security or production-capacity checks.
