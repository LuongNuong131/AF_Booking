# Deploy AF Booking từ đầu: TiDB → Render → Vercel

Hệ thống gồm ba phần: TiDB lưu dữ liệu, Render chạy FastAPI, Vercel chạy giao diện
Vue. Vercel không chạy backend Python và không kết nối trực tiếp tới database.

Đọc hướng dẫn này trên nhánh `main` mới nhất. Các tên `YOUR-API`, `YOUR-APP`,
`<tidb-host>`, `<encoded-user>`, `<encoded-password>` là chỗ cần thay bằng giá trị thật.
Không nhập nguyên ví dụ vào cấu hình production.

## 1. Chuẩn bị TiDB Cloud

Nếu đã có Host/Port/Username thì cluster TiDB đã được tạo; không cần tạo cluster
mới. Database `booking_tracker` và các bảng của ứng dụng vẫn cần được kiểm tra/tạo.

1. Vào [TiDB Cloud Console](https://tidbcloud.com/), mở cluster đang dùng.
2. Nếu mật khẩu database đã được chia sẻ trong chat, đổi mật khẩu trong phần quản
   lý user của TiDB trước khi cấu hình deployment. Lưu mật khẩu mới trong trình
   quản lý mật khẩu; không đưa vào GitHub hoặc biến `VITE_*`.
3. Mở **Connect** để lấy Host, Port, Username chính xác. Giữ nguyên prefix và phần
   `.root` nếu username do TiDB cấp có định dạng đó. Port của cấu hình này là `4000`.
4. Trong SQL Editor của TiDB (nếu có), hoặc MySQL client kết nối từ màn hình
   Connect với TLS bật, chạy:

   ```sql
   CREATE DATABASE IF NOT EXISTS booking_tracker
     CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
   SHOW DATABASES LIKE 'booking_tracker';
   ```

   Lệnh này chỉ tạo database, chưa tạo bảng. Alembic ở bước sau tạo các bảng.
5. Nếu cluster có IP allowlist/Network Access, cho phép IP outbound của Render.
   Lấy danh sách từ trang **Connect → Outbound** của service Render sau khi tạo.
   Nếu chạy migration/seed từ máy cá nhân, cho phép thêm IP public hiện tại của máy.
6. Tạo giá trị `DATABASE_URL` theo mẫu:

   ```text
   mysql+aiomysql://<encoded-user>:<encoded-password>@<tidb-host>:4000/booking_tracker?charset=utf8mb4
   ```

   Encode riêng username/password nếu có ký tự đặc biệt như `@`, `:`, `/`, `#`,
   `%`, `?`; không encode toàn bộ URL. Không thêm `ssl=false`. Đặt `DB_SSL=true`:
   ứng dụng kiểm tra chứng chỉ và hostname bằng CA hệ thống. Nếu TiDB yêu cầu CA
   riêng, dùng secret file và `DATABASE_SSL_CA`; không tắt TLS để xử lý lỗi kết nối.

## 2. Chọn cách chạy backend Render

Repo có sẵn `render.yaml` với **Starter trả phí**, region Singapore, một instance
và một worker. Xem giá hiện tại trong Render trước khi tạo. Blueprint tự sinh JWT
secret và chạy `alembic upgrade head` trước mỗi deployment.

Nếu chọn **Free**, xem mục 4: gói này không có Render Shell và pre-deploy command;
cần chạy migration/seed từ máy cá nhân. Không import Blueprint Starter rồi kỳ vọng
service tự thành Free. Free có thể ngủ khi không có traffic; lịch nhắc việc không
chạy trong lúc service ngủ.

## 3. Render bằng Blueprint Starter

1. Đăng nhập [Render Dashboard](https://dashboard.render.com/).
2. Chọn **New → Blueprint**, kết nối GitHub và chọn repo
   `LuongNuong131/AF_Booking`, branch `main`.
3. Dùng file `render.yaml` ở thư mục gốc, xem lại region/plan.
4. Điền các giá trị Render yêu cầu:

   | Biến | Giá trị |
   | --- | --- |
   | `DATABASE_URL` | URL TiDB tạo ở mục 1 |
   | `CORS_ORIGINS` | `[]` trong lần đầu, vì chưa có domain Vercel |

   `[]` là JSON hợp lệ, tạm thời không cho phép browser origin nào. Sau khi có
   domain Vercel, bắt buộc cập nhật lại ở mục 6.
5. Các giá trị còn lại Blueprint đã đặt: `APP_ENV=production`, `DB_SSL=true`,
   `PYTHON_VERSION=3.12.12`, `BUSINESS_TIMEZONE=Asia/Ho_Chi_Minh`, pool 5,
   `DB_MAX_OVERFLOW=0`. `JWT_SECRET_KEY` được sinh ngẫu nhiên.
6. Tạo Blueprint. Nếu TiDB có allowlist, bổ sung outbound IP của service như mục 1
   rồi deploy lại nếu lần đầu bị chặn kết nối database.
7. Xem log: build cài requirements, pre-deploy chạy migration tới `head`, sau đó
   Uvicorn khởi động. Khi service Live, copy URL Render cấp, ví dụ
   `https://booking-tracker-api-xxxx.onrender.com`. Suffix thực tế có thể khác.
8. Mở hai URL, thay `YOUR-API` bằng hostname thật:

   ```text
   https://YOUR-API.onrender.com/health
   https://YOUR-API.onrender.com/api/v1/ready
   ```

   Kết quả tương ứng:

   ```json
   {"status":"ok","service":"booking-tracker-api"}
   ```

   ```json
   {"status":"ok","database":"connected"}
   ```

   `/health` thành công chỉ chứng minh process đang chạy. Migration phải thành
   công và `/api/v1/ready` phải báo database connected trước khi dùng ứng dụng.
9. Tạo tài khoản quản trị đầu tiên. Trong service Render → **Environment**, thêm:

   ```dotenv
   ADMIN_USERNAME=admin
   ADMIN_PASSWORD=<mat-khau-tam-do-ban-tu-dat>
   ```

   Chọn mật khẩu ngẫu nhiên ít nhất 12 ký tự, tối đa 128 ký tự, khác username.
   Save/redeploy để environment mới có hiệu lực. Mở **Shell** của service, chạy:

   ```sh
   alembic current
   python -m app.scripts.seed
   ```

   Migration hiện tại là `0012`. Seed tạo status mặc định và admin còn thiếu;
   chạy lại không đặt lại password của tài khoản đã có. Không dùng seed làm lệnh
   reset mật khẩu. Sau khi seed xong, xóa `ADMIN_PASSWORD`/`ADMIN_USERNAME` khỏi
   environment Render và save/redeploy; tài khoản đã nằm trong database.

Không tăng số instance/worker: session cache, realtime, locks và scheduler đang
được thiết kế cho một process.

## 4. Phương án Render Free

Bỏ qua mục này nếu đã làm mục 3.

### 4.1 Tạo schema và admin trên máy cá nhân

Cài Git và Python **3.12**, sau đó mở Terminal:

```sh
git clone https://github.com/LuongNuong131/AF_Booking.git
cd AF_Booking/backend
python3.12 -m venv .venv
```

Trên Windows, dùng `py -3.12 -m venv .venv`. Các lệnh `.venv/bin/python` bên dưới
đổi thành `.venv\Scripts\python.exe`; `.venv/bin/alembic` đổi thành
`.venv\Scripts\alembic.exe`.

```sh
.venv/bin/python -m pip install --require-hashes -r requirements.txt
.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Lưu chuỗi ngẫu nhiên vừa sinh để dùng làm `JWT_SECRET_KEY`. Tạo file `backend/.env`
bằng editor, điền giá trị thật trên máy cá nhân:

```dotenv
APP_ENV=production
DATABASE_URL=mysql+aiomysql://<encoded-user>:<encoded-password>@<tidb-host>:4000/booking_tracker?charset=utf8mb4
DB_SSL=true
JWT_SECRET_KEY=<chuoi-ngau-nhien-vua-sinh>
CORS_ORIGINS=[]
BUSINESS_TIMEZONE=Asia/Ho_Chi_Minh
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<mat-khau-tam-do-ban-tu-dat>
```

`.env` đã nằm trong `.gitignore`; không force-add file này. Cho phép IP public của
máy trong TiDB nếu cluster giới hạn network. Từ thư mục `backend`, chạy:

```sh
.venv/bin/alembic upgrade head
.venv/bin/alembic current
.venv/bin/python -m app.scripts.seed
```

Kết quả cần có revision `0012` và lần seed đầu `admin created: True`. Nếu có lỗi,
xử lý kết nối/TLS/allowlist trước; không dùng `alembic stamp head` để bỏ qua tạo bảng.

### 4.2 Tạo Web Service Free

Render → **New → Web Service** → kết nối repo → cấu hình:

| Trường | Giá trị |
| --- | --- |
| Branch | `main` |
| Language/Runtime | Python |
| Region | Singapore |
| Root Directory | `backend` |
| Instance Type | Free |
| Build Command | `pip install --require-hashes -r requirements.txt` |
| Start Command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1 --no-access-log --ws websockets-sansio --ws-max-size 4096` |
| Health Check Path | `/health` |

Trong Environment, thêm:

```dotenv
PYTHON_VERSION=3.12.12
APP_ENV=production
DATABASE_URL=<URL-TiDB-da-dung-o-tren>
DB_SSL=true
JWT_SECRET_KEY=<chuoi-ngau-nhien-da-luu>
CORS_ORIGINS=[]
BUSINESS_TIMEZONE=Asia/Ho_Chi_Minh
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=0
DB_POOL_RECYCLE_SECONDS=280
```

Không cần đưa `ADMIN_PASSWORD` lên Render Free vì đã seed từ máy cá nhân. Tạo
service, cho phép outbound IP trong TiDB nếu cần, đợi Live rồi kiểm tra hai URL
health/ready như mục 3. Lưu URL HTTPS Render cấp.

Khi cập nhật code có migration mới, lấy code mới và chạy `alembic upgrade head`
từ máy trước khi deploy backend. Không chạy migration trong build command.

## 5. Tạo frontend Vercel

Chỉ làm bước này sau khi Render đã có URL thật và database đã sẵn sàng.

1. Vào [Vercel Dashboard](https://vercel.com/dashboard) → **Add New → Project**.
2. Import repo `LuongNuong131/AF_Booking`, branch `main` mới nhất.
3. Đặt:

   | Trường | Giá trị |
   | --- | --- |
   | Framework Preset | Vite |
   | Root Directory | `frontend` |
   | Node.js Version | `24.x` |
   | Install Command | `npm ci` |
   | Build Command | `npm run build` |
   | Output Directory | `dist` |

4. Trong **Environment Variables**, thêm:

   ```dotenv
   VITE_API_URL=https://YOUR-API.onrender.com/api/v1
   ```

   Thay bằng URL Render thật, có hậu tố `/api/v1`, không có dấu nháy. Chọn scope
   **Production**. Nếu dùng Preview thì thêm cả Preview; CORS của backend vẫn cần
   cho phép chính xác domain preview đó.
5. Có thể để trống `VITE_WS_URL`; code tự suy ra:

   ```dotenv
   VITE_WS_URL=wss://YOUR-API.onrender.com/api/v1/ws
   ```

   Nếu tự điền thì phải có `wss://` và `/api/v1/ws`. Không điền URL database hoặc
   mật khẩu vào bất kỳ biến `VITE_*` nào. Để trống Sentry khi chưa dùng.
6. Bấm **Deploy**. Build mới tự tạo CSP đúng API/WSS cùng SPA fallback và cache
   PWA qua Build Output API; không cần chạy `configure:csp` hoặc commit URL backend.
7. Khi Ready, copy **domain production** trong Settings → Domains, ví dụ
   `https://af-booking-xxxx.vercel.app`. Dùng domain ổn định này cho CORS ở mục 6.

Nếu sửa project Vercel cũ đã build lỗi: kiểm tra lại Root Directory, vào Settings
→ Environment Variables thêm `VITE_API_URL` cho Production, rồi deploy commit
`main` mới nhất từ Git. Đừng redeploy riêng commit cũ `57bc8cc`, vì commit đó còn
cấu hình CSP thủ công. Thay biến môi trường luôn cần build/deploy mới; refresh
trình duyệt không cập nhật giá trị đã được bundle.

## 6. Kết nối domain Vercel với Render

Render → service backend → **Environment** → đổi:

```dotenv
CORS_ORIGINS=["https://YOUR-APP.vercel.app"]
```

Thay domain thật, giữ nguyên định dạng JSON. Origin không có path, dấu `/` cuối
hoặc wildcard. Save/redeploy và đợi service Live. Nếu dùng domain riêng, thêm rõ:

```dotenv
CORS_ORIGINS=["https://YOUR-APP.vercel.app","https://booking.example.com"]
```

Origin của kết nối WebSocket dùng cùng allowlist này.

## 7. Kiểm tra sau cùng

1. `/health` và `/api/v1/ready` trả kết quả như mục 3; log migration đã tới head.
2. Vào domain Vercel, đăng nhập bằng admin đã seed.
3. Đổi mật khẩu tạm khi ứng dụng yêu cầu; account seed lần đầu bắt buộc đổi mật khẩu.
4. Mở trang bên trong rồi nhấn refresh để kiểm tra SPA fallback.
5. Kiểm tra trạng thái realtime/Live sau khi đăng nhập và đổi mật khẩu.
6. Nếu lỗi, mở DevTools → Network/Console và xem Render Logs. Phân biệt:

   | Dấu hiệu | Kiểm tra |
   | --- | --- |
   | `VITE_API_URL is required for production` | Biến trên Vercel, scope Production/Preview, redeploy commit mới |
   | Build vẫn đòi `configure:csp` | Đang build code cũ, kiểm tra SHA/branch của deployment |
   | API 503 ở `/api/v1/ready` | URL DB, mật khẩu, database có tồn tại, TLS, TiDB allowlist |
   | Log báo bảng không tồn tại | `alembic upgrade head` chưa chạy đúng database |
   | CORS hoặc WebSocket bị chặn | `CORS_ORIGINS` phải chứa domain đang mở; Save/redeploy Render |
   | Browser báo CSP chặn API | Kiểm tra deployment mới, `VITE_API_URL`, `VITE_WS_URL`; bỏ cache/site data của bản cũ nếu cần |
   | Login không đúng | Đã seed chưa, dùng đúng username/password đã tự đặt; seed lại không reset password |
   | Render Free mất thời gian ở lần mở đầu | Service đang khởi động lại sau khi ngủ |

Push code và build cục bộ thành công không chứng minh deployment production đã
hoạt động. TiDB, Render, Vercel và tài khoản admin cần hoàn tất các bước trên.
