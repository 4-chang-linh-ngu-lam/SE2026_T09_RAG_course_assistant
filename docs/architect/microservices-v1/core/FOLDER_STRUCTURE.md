# Quy ước tổ chức mã nguồn Core Service

**Trạng thái:** BASELINE QUY ƯỚC THƯ MỤC; cập nhật 23/10/2026: Common, Identity, Classroom, Social/Calendar, Notification và Administration/import đã có triển khai. Cây dưới đây vẫn chứa mục tiêu lịch sử; đối chiếu source/API_CONTRACT cho file và endpoint thực tế. **Phạm vi:** `services/core/` trong **một monorepo**; Core là **một FastAPI microservice**, không tách module nội bộ thành các service riêng.

## 1. Mục tiêu và cách đọc
- Người mới biết đặt file ở đâu, mỗi thư mục chịu trách nhiệm gì, ai thường sửa.
- AI coding agent chỉ đọc tài liệu này khi task liên quan Core; đối chiếu `BUSINESS_RULES.md`, `core/DESIGN.md` và `core/API_CONTRACT.md` trước khi triển khai. **Tài liệu này là quy ước tổ chức code, không tự tạo thêm business rule hay endpoint.**
- Tách theo **chức năng nghiệp vụ** (feature-first), không gom toàn bộ router/model/schema của mọi tính năng vào một thư mục.
- Không tạo tất cả file rỗng; tạo module/file khi có tính năng thực tế. Tên thư mục và phân công dưới đây có thể được điều chỉnh khi nhóm duyệt.

## 2. Cây thư mục mục tiêu (comment từng khu vực)

```text
services/core/                         # Một service FastAPI; build/chạy/test độc lập với service khác
├── app/                               # Mã Python chạy trong Core
│   ├── __init__.py
│   ├── main.py                        # Khởi tạo FastAPI, middleware, đăng ký router; file shared, ít sửa
│   ├── bootstrap.py                   # Hàm lắp ghép router/module tập trung, tránh mọi người sửa main.py
│   ├── common/                        # Hạ tầng chung, KHÔNG chứa logic nghiệp vụ riêng từng module
│   │   ├── config.py                  # Đọc/cấu hình biến môi trường, không hardcode secret
│   │   ├── db.py                      # Engine, session, transaction và dependency DB
│   │   ├── security.py                # JWT, hash mật khẩu, refresh-token helpers
│   │   ├── auth_dependencies.py       # Lấy người dùng hiện tại; kiểm tra trạng thái tài khoản/phiên
│   │   ├── errors.py                  # Cấu trúc lỗi HTTP thống nhất, correlation ID
│   │   ├── pagination.py              # Quy ước phân trang dùng chung
│   │   └── audit.py                   # Hạ tầng ghi audit; không lưu nội dung chat riêng tư
│   ├── modules/                        # Mỗi thư mục là một miền chức năng, KHÔNG phải microservice
│   │   ├── identity/                  # TV1: username/activation Student, email staff, school context, JWT
│   │   │   ├── router.py              # Endpoint HTTP của Identity
│   │   │   ├── schemas.py             # Pydantic request/response; không trả password_hash
│   │   │   ├── models.py              # SQLAlchemy ORM thuộc Identity
│   │   │   ├── service.py             # Đăng nhập/thu hồi phiên; đăng ký email legacy nội bộ, HTTP bị chặn
│   │   │   ├── repository.py          # Truy vấn và ghi dữ liệu Identity
│   │   │   └── public.py              # Giao diện nội bộ được module khác phép gọi
│   │   ├── classroom/                 # TV2: School, roster, lớp môn học, AUTO/MANUAL, teaching assignment
│   │   │   ├── router.py
│   │   │   ├── schemas.py
│   │   │   ├── models.py
│   │   │   ├── service.py             # Admin sync/chuyển lớp, phân công, archive/restore; transaction
│   │   │   ├── repository.py
│   │   │   ├── permissions.py         # Quyền theo lớp, không chỉ dựa trên role toàn hệ thống
│   │   │   └── public.py              # Ví dụ: check_class_access(...) cho các module khác
│   │   ├── social/                    # TV3: chức năng tương tác lớp
│   │   │   ├── feed/                  # Bài đăng bảng tin, ẩn/xóa theo quyền
│   │   │   ├── comments/              # Bình luận bài đăng, kiểm tra quyền và trạng thái bài
│   │   │   └── calendar/              # Sự kiện lịch lớp; KHÔNG sở hữu deadline Assessment
│   │   ├── notification/              # TV4: thông báo trong ứng dụng, trạng thái đã đọc
│   │   │   ├── router.py
│   │   │   ├── schemas.py
│   │   │   ├── models.py
│   │   │   ├── service.py
│   │   │   └── repository.py
│   │   └── administration/            # TV4 phối hợp TV1/TV2: quản trị user/role/class, audit can thiệp
│   │       ├── router.py
│   │       ├── schemas.py
│   │       └── service.py             # Gọi public interfaces; tránh sao chép logic Identity/Classroom
│   └── integrations/                  # Biên giao tiếp với các microservice KHÁC (khi cần)
│       ├── contracts.py               # DTO/event contract dùng xuyên service; có version
│       └── events.py                  # Phát/nhận sự kiện, idempotency; chỉ tạo khi triển khai
├── migrations/                        # Alembic migrations của Core, không sửa schema service khác
│   ├── env.py                         # Cấu hình metadata và kết nối migration
│   └── versions/                      # Một migration cho mỗi thay đổi schema hợp lý
├── tests/                             # Test nằm gần phạm vi người phụ trách
│   ├── identity/                       # Student activation/staff email, refresh/revoke, school scope, lock
│   ├── classroom/                      # Admin enrollment/transfer, cross-school/class, assignment, archive
│   ├── social/                         # Feed, comments, calendar
│   ├── notification/                   # Tạo/đọc thông báo và kiểm tra quyền
│   ├── administration/                 # Admin action và audit
│   ├── integration/                    # API + DB + quyền + migration; test liên module
│   └── conftest.py                     # Fixtures dùng chung; thay đổi phải review
├── pyproject.toml                      # Dependencies, formatter, linter, pytest config
├── alembic.ini                         # Cấu hình Alembic
├── Dockerfile                          # Đóng gói CHỈ Core
└── README.md                           # Cách chạy Core, migration, test, cấu hình
```

Biến môi trường mẫu dùng `.env.example` tại root monorepo, không phải một file Core riêng; không chứa secret thật.

**Lưu ý:** các file bên trong `feed/`, `comments/`, `calendar/` có thể áp dụng cùng bộ `router.py`, `schemas.py`, `models.py`, `service.py`, `repository.py` khi thực sự cần. `administration/` có thể dùng model AuditEvent thuộc hạ tầng audit hoặc module admin tùy thiết kế DB được duyệt.

## 3. Trách nhiệm từng tầng bên trong một module

| Thành phần | Được làm | Không nên làm |
|---|---|---|
| `router.py` | Nhận request, dependency, gọi service, trả response | Viết truy vấn SQL hay nghiệp vụ dài |
| `schemas.py` | Pydantic input/output, validation cấu trúc | Trả trường bí mật hoặc chứa ORM logic |
| `models.py` | Bảng, quan hệ, constraint ORM | Gọi API hay xử lý HTTP |
| `service.py` | Nghiệp vụ, transaction boundary, phối hợp module qua `public.py` | Phụ thuộc vào FastAPI request object nếu không cần |
| `repository.py` | Query, insert/update/delete theo interface rõ | Quyết định quyền người dùng thay service |
| `permissions.py` | Chính sách quyền của miền nghiệp vụ | Tin role trong JWT mà bỏ qua trạng thái hiện hành |
| `public.py` | API Python ổn định để module khác gọi | Export mọi hàm nội bộ |

Ví dụ: `social/feed/service.py` muốn xác minh quyền đăng bài thì gọi `classroom/public.py`, **không tự query bảng membership**. Trong Core, gọi Python nội bộ, không HTTP loopback.

## 4. Quy tắc giảm Git conflict cho 4 người

| Người phụ trách chính (đã chọn) | Vùng code ưu tiên | Vùng phối hợp |
|---|---|---|
| TV1 | `modules/identity/` | `common/security.py`, `auth_dependencies.py` |
| TV2 | `modules/classroom/` | Hợp đồng quyền `classroom/public.py` |
| TV3 | `modules/social/` | Tích hợp quyền lớp, notification events |
| TV4 | `modules/notification/`, `modules/administration/` | Docker/CI, test tích hợp, audit |

- **Shared files có owner/reviewer:** `main.py`, `bootstrap.py`, `common/`, `pyproject.toml`, `migrations/env.py`, `tests/conftest.py`, `Dockerfile`. Trước khi sửa, trao đổi trong Issue/PR; không tự thêm dependency hay đổi interface của người khác.
- Mỗi thành viên có thể làm **vertical slice** gồm backend, frontend và test theo feature; bảng phân công không buộc một người chỉ code Backend.
- Mỗi feature branch ngắn hạn, PR theo chức năng đủ kiểm thử; **không cần mỗi file hoặc mỗi task một commit**. Review chéo trước merge; không dùng commit giả.
- Migration: mỗi người tạo revision riêng, **không sửa migration đã merge/được áp dụng**. Nếu có nhiều head, phối hợp tạo merge revision sau khi kiểm tra thứ tự phụ thuộc; không tự sửa lịch sử.
- Để giảm xung đột đăng ký router: module export `router`, một owner cập nhật `bootstrap.py` khi tích hợp. Tránh auto-discovery bằng import động không rõ ràng.
- Trước khi thay đổi `public.py`, schema chung hoặc permission: thông báo consumer, sửa test hợp đồng, rồi mới merge.

## 5. Luồng phụ thuộc và quy tắc import

```text
HTTP request → router → service → repository → PostgreSQL (Core)
                          │
                          └→ module_khác.public → service module khác
```

- `identity` không import `social`; `classroom` không import `social`; `social` và `notification` có thể phụ thuộc giao diện công khai của `identity/classroom`.
- Tránh vòng import: nếu hai module cần gọi nhau, chuyển hợp đồng sang interface chung hoặc thay đổi luồng điều phối; **không** cho phép import trực tiếp `repository.py` của nhau.
- Tách **service-level permission** (Core xác nhận membership) và **document-level permission** (Document xác nhận chia sẻ hiện hành); AI phải kiểm tra cả hai khi truy hồi.
- Core không sở hữu điểm, đề Assessment, tài liệu nguồn, chat AI hoặc mastery. Lịch chỉ phản ánh deadline do Learning sở hữu; không cập nhật deadline chính thức từ Core.

## 6. Ví dụ một yêu cầu từ đầu đến cuối

**Admin đồng bộ ghi danh AUTO (luồng mục tiêu, chưa triển khai):**
1. `classroom/router.py` nhận yêu cầu Admin; actor và school scope lấy từ backend authentication.
2. `classroom/service.py` kiểm tra quyền hiện hành, lớp/mode và roster theo hợp đồng preview/confirm được duyệt.
3. `classroom/repository.py` cập nhật membership trong transaction, giữ lịch sử và constraint chống trùng; lớp MANUAL không bị ghi đè.
4. Audit và outbox được ghi cùng transaction qua interface đã thống nhất; consumer Notification xử lý sau commit, retry/dedup an toàn.
5. `classroom/public.py` cung cấp action-based access cho Social/Administration; service khác dùng internal API có service credential.
6. `tests/classroom/` kiểm tra Admin-only, cross-school/class, sync cạnh tranh, rollback/outbox và kết thúc enrollment giữ lịch sử cá nhân hợp lệ.

Schema/payload, preview và hiệu lực chuyển lớp còn PENDING DESIGN trong [Core Design](DESIGN.md)/[API Contract](API_CONTRACT.md); không dùng ví dụ này làm API đã phát hành. JoinRequest/teacher approval và ownership transfer không thuộc MVP.

## 7. Quy ước cho AI coding agent

1. Đọc Business Rules và thiết kế/hợp đồng Core liên quan, rồi đọc tài liệu này; không coi cây thư mục mục tiêu là code đã tồn tại.
2. Xác định module sở hữu nghiệp vụ trước khi tạo file; không tạo `utils.py` hoặc `helpers.py` dùng chung chỉ để tiện.
3. Chỉ sửa file trong phạm vi task; nếu phải đổi shared file/public interface, nêu lý do và yêu cầu review.
4. Không tự ý thay đổi JWT policy, permission, schema liên module, Business Rules hoặc API đã chốt.
5. Code phải có test tương ứng; chạy test thật trước khi báo hoàn thành.
6. Không tạo file tạm/placeholder vô nghĩa; không đưa secret, dữ liệu cá nhân hay chat riêng tư vào log/test fixture.
7. Không tự push main, merge PR hay thay đổi bảo vệ nhánh nếu chưa được cho phép.
8. Khi cấu trúc triển khai khác tài liệu, cập nhật chính phần liên quan của tài liệu này trong PR; tránh tài liệu lỗi thời.

## 8. Quy tắc khi tạo skeleton
- Giữ `app/common/` và `app/modules/` đúng cấu trúc; đổi phải qua PR cập nhật thiết kế.
- TV1–TV4 là **owner chính**; mỗi người vẫn thực hiện frontend/test theo feature.
- Schema/state machine/quyền theo `DESIGN.md`; API theo `API_CONTRACT.md`; sinh OpenAPI từ FastAPI và kiểm tra contract khi triển khai.
- `social`, `notification`, `administration` thuộc G1–G2, phải hoàn thành trước khi chuyển sang Document/AI.

**Nguyên tắc cuối:** ít file dùng chung, ownership rõ, interface ổn định, PR nhỏ, commit có ý nghĩa. Không cố tối ưu conflict bằng cách sao chép logic hoặc bỏ kiểm tra quyền.
