# RAG Course Assistant — Kiến trúc Microservices

**Phiên bản:** 1.0.0-draft | **Ngày:** 10/10/2026 | **Trạng thái:** Đã chọn định hướng Microservices; các quyết định kỹ thuật và ngưỡng kiểm thử chưa duyệt.

**Định hướng:** Thiết kế hệ thống theo Microservices ngay từ đầu, không phải tài liệu chuyển đổi từ Monolith. **Nguồn nghiệp vụ có hiệu lực:** [Quy tắc nghiệp vụ](../BUSINESS_RULES.md). **Cơ sở lựa chọn:** [ADR-001](ADR-001.md). **Tiêu chí kiểm chứng:** [Thuộc tính chất lượng](QUALITY_ATTRIBUTES.md).

> [ĐÃ CHỐT] là quy tắc nghiệp vụ hoặc mức ưu tiên đã thống nhất; [ĐỀ XUẤT] là quyết định kỹ thuật chưa duyệt; [CHƯA CHỐT] là vấn đề cần thảo luận. Không tự suy diễn đã chọn công nghệ hoặc đã kiểm thử thành công.

**Hướng dẫn triển khai cho nhóm:** [Lộ trình Core-first](IMPLEMENTATION_ROADMAP.md) · [Thiết kế Core](core/DESIGN.md) · [Hợp đồng API Core](core/API_CONTRACT.md). Các tài liệu chi tiết này đều là **[ĐỀ XUẤT]**, chưa phải đặc tả được phê duyệt.\n\n## 1. Mục tiêu và phạm vi
RAG Course Assistant là nền tảng **ưu tiên học tập thông minh**: trung tâm tri thức môn học, trợ giảng AI có trích dẫn, luyện tập, đánh giá chính thức, mô hình năng lực người học và gợi ý học tập cá nhân hóa. Chức năng quản lý lớp học hỗ trợ các mục tiêu này. Có ba vai trò đăng nhập: Quản trị viên, Giảng viên, Sinh viên. Một môn có thể có nhiều lớp; sinh viên có thể học nhiều lớp. Ưu tiên ứng dụng Web; Mobile chỉ xem xét sau khi Web ổn định. [A, C, D, E, G, O]

## 2. Các dịch vụ nghiệp vụ
| Dịch vụ | Phạm vi nghiệp vụ | Dữ liệu sở hữu |
|---|---|---|
| **Core** (Nền tảng lõi) | Tài khoản, vai trò, lớp, thành viên, duyệt vào lớp, đồng giảng viên, bảng tin, thông báo, điều phối quản trị | Người dùng, lớp, quyền thành viên, phiên đăng nhập, sự kiện quản trị lõi |
| **Document** (Tài liệu) | Thư viện cá nhân giảng viên, tệp gốc, phiên bản, chia sẻ, quyền truy cập, xem/tải, trạng thái xử lý | Tài liệu, phiên bản, quyền chia sẻ, tệp gốc, tác vụ xử lý |
| **Learning** (Hoạt động học tập) | Ngân hàng câu hỏi, luyện tập, bài đánh giá, bài tập, lượt làm, bài nộp, điểm, phúc khảo | Đề và phiên bản, câu trả lời, lượt làm, điểm và lịch sử sửa điểm |
| **AI** (Trợ giảng thông minh) | RAG, truy hồi, hội thoại, trích dẫn, nhúng và chỉ mục tìm kiếm | Hội thoại, dữ liệu truy hồi dẫn xuất, phiên bản nhúng/chỉ mục |
| **Learner Intelligence** (Phân tích người học) | Bằng chứng học tập, mức độ nắm vững chủ đề, gợi ý, thống kê | Hồ sơ năng lực, dữ liệu tổng hợp, gợi ý và dấu vết bằng chứng |

Đây là **5 ranh giới nghiệp vụ đề xuất**, không có nghĩa mọi chức năng phải chạy trên 5 máy vật lý riêng. Tác vụ nền có thể có nhiều tiến trình trong phạm vi dịch vụ sở hữu.

## 3. Nguyên tắc thiết kế
1. Mỗi dịch vụ có hợp đồng giao tiếp và quyền sở hữu dữ liệu riêng; không đọc/ghi trực tiếp bảng của dịch vụ khác.
2. Bài nộp, điểm chính thức và lịch sử sửa điểm nhất quán trong giao dịch của Learning; phân tích năng lực được cập nhật bất đồng bộ.
3. AI không quyết định điểm chính thức. Câu hỏi do AI sinh phải được giảng viên duyệt; tắt trợ giảng tích hợp trong kỳ đánh giá chính thức. [D1, D4–D6]
4. Quyền truy cập hiện tại được ưu tiên; phải kiểm tra quyền trước khi đưa đoạn tài liệu vào ngữ cảnh mô hình và trước khi mở nguồn trích dẫn. Nếu không xác minh được quyền thì từ chối thao tác nhạy cảm. [B6–B7, H4, K3]
5. AI hỏng không được làm hỏng các chức năng không phụ thuộc AI; không cam kết chịu được sự cố hạ tầng chung nếu chưa có cơ chế tương ứng.
6. Có giới hạn thời gian chờ, tài nguyên, cơ chế thử lại an toàn, quan sát hệ thống và kiểm thử hợp đồng.
7. Giao diện Web và các dịch vụ Backend giao tiếp qua API có phiên bản.

## 4. Sơ đồ kiến trúc
```mermaid
flowchart TB
  Web[Giao diện Web] --> Gateway[Cổng API]
  Gateway --> Core[Dịch vụ Core]
  Gateway --> Doc[Dịch vụ Document]
  Gateway --> Learn[Dịch vụ Learning]
  Gateway --> AI[Dịch vụ AI]
  Gateway --> Intel[Dịch vụ Learner Intelligence]
  Core --> CDB[(Dữ liệu Core)]
  Doc --> DDB[(Dữ liệu Document)]
  Doc --> Store[(Kho lưu tệp gốc)]
  Learn --> LDB[(Dữ liệu Learning)]
  AI --> ADB[(Dữ liệu AI)]
  AI --> Vector[(Chỉ mục vector)]
  Intel --> IDB[(Dữ liệu năng lực)]
  Learn --> Outbox[Hộp sự kiện giao dịch]
  Outbox --> Bus[(Hàng đợi / Bộ chuyển sự kiện)]
  Doc --> Bus
  Core --> Bus
  Bus --> Intel
  Bus --> AI
  Doc --> Worker[Tiến trình xử lý tài liệu]
  Worker --> AI
  AI --> LLM[Mô hình ngôn ngữ]
  AI -. kiểm tra thành viên .-> Core
  AI -. kiểm tra quyền nguồn .-> Doc
  Learn -. kiểm tra quyền lớp .-> Core
  Doc -. kiểm tra quyền lớp .-> Core
```

Các phụ thuộc kiểm tra quyền là đường xử lý nhạy cảm: khi nguồn xác minh không khả dụng, hệ thống từ chối thay vì sử dụng quyền cũ một cách thiếu kiểm soát.

## 5. Dữ liệu và tính nhất quán
- Mỗi dịch vụ sở hữu một cơ sở dữ liệu hoặc vùng dữ liệu riêng và tài khoản truy cập riêng. **Có thể dùng chung một máy chủ PostgreSQL**, nhưng không chia sẻ bảng hay khóa ngoại xuyên dịch vụ. Loại cơ sở dữ liệu cuối cùng vẫn [CHƯA CHỐT].
- Tệp gốc và quyền chia sẻ do Document quản lý. AI chỉ sở hữu dữ liệu dẫn xuất để truy hồi; metadata trong chỉ mục vector **không phải nguồn xác thực quyền**.
- Giao tiếp bất đồng bộ dùng cơ chế **Transactional Outbox (hộp sự kiện cùng giao dịch)**, phát sự kiện ít nhất một lần và **Idempotent Consumer (bộ nhận xử lý lặp an toàn)**.
- Sự kiện phải có mã định danh, phiên bản cấu trúc, thời điểm, nguồn phát, đối tượng, phiên bản đối tượng và mã truy vết. Không phát tán nội dung hội thoại riêng tư hay nguyên văn tài liệu trong sự kiện chung.
- Có hàng đợi lỗi, xử lý lại, đối soát và chống sự kiện đến sai thứ tự. Không tuyên bố toàn hệ thống có bảo đảm phát sự kiện đúng một lần tuyệt đối.
- Các mã định danh quan trọng: `user_id`, `class_id`, `document_id`, `document_version_id`, `activity_version_id`, `attempt_id`, `grade_revision_id`, `event_id`, `correlation_id`.

## 6. Các luồng nghiệp vụ trọng tâm
### 6.1. Tải tài liệu và lập chỉ mục
1. Giảng viên tải tệp lên; Document xác minh quyền, kiểm tra định dạng và lưu tệp gốc cùng phiên bản bất biến.
2. Document tạo tác vụ; tiến trình nền trích xuất, chuẩn hóa, chia đoạn và tạo biểu diễn nhúng.
3. AI lập **bản chỉ mục ứng viên** tách biệt, kiểm tra hoàn chỉnh và phản hồi kết quả.
4. Chỉ công bố phiên bản đã xử lý thành công; phiên bản mới lỗi không thay thế phiên bản hợp lệ trước đó.
5. Thu hồi chia sẻ có hiệu lực tại bước xác minh quyền, không phải chờ xóa vector. [B4–B7, H3]

[CHƯA CHỐT] Giao thức xác nhận và chuyển đổi nguyên tử giữa bản chỉ mục ứng viên và bản đang hoạt động.

### 6.2. Hỏi trợ giảng AI
1. Xác thực người dùng, lớp đang chọn và quyền thành viên hiện tại.
2. Xác định tài liệu và phiên bản hợp lệ, truy hồi các đoạn ứng viên.
3. **Xác minh lại quyền từng nguồn trước khi đưa nội dung vào lời nhắc của mô hình**; loại bỏ nguồn không được phép.
4. Sinh câu trả lời có căn cứ, phân biệt kiến thức chung, kiểm tra trích dẫn và nói rõ khi thiếu bằng chứng.
5. Kiểm tra quyền khi mở nguồn; lịch sử hội thoại phải che nội dung mất quyền. Lớp đã lưu trữ không được hỏi mới. [C1–C6, H4–H5, K3]

### 6.3. Nộp bài, chấm và sửa điểm
1. Learning xác minh quyền, phiên bản đề bất biến, thời hạn theo đồng hồ máy chủ; lưu câu trả lời đã xác nhận.
2. Nộp bài kèm khóa chống lặp; một giao dịch ghi trạng thái bài nộp và sự kiện trong hộp sự kiện.
3. Trả xác nhận mà **không chờ AI hoặc Learner Intelligence**; hết giờ tự nộp các câu đã lưu, mất mạng chỉ tiếp tục nếu còn thời gian. [I1–I4, O3]
4. Câu khách quan chấm theo quy tắc; giảng viên duyệt điểm chủ quan/bài tập. Sửa điểm ghi người sửa, lý do, thời gian và phiên bản. [D4–D5, I6]
5. Learner Intelligence nhận sự kiện kết quả đã xác nhận; xử lý lặp và sai thứ tự theo phiên bản mới nhất. [J3]

### 6.4. Phân tích năng lực và gợi ý
- Bằng chứng gắn chủ đề/mục tiêu học tập đã được giảng viên xác nhận. Không coi hỏi lặp là bằng chứng năng lực độc lập.
- Khi dữ liệu thiếu, hiển thị **“Chưa đủ dữ liệu”**; gợi ý chỉ hỗ trợ, sinh viên tự quyết định. [E3–E6, J1–J5]
- Thống kê chủ đề hội thoại AI phải ẩn nhóm có dưới 5 sinh viên tham gia phân biệt và áp dụng ẩn bổ sung. [O6]

## 7. Hợp đồng giao tiếp
- [ĐỀ XUẤT] API HTTP/JSON có phiên bản, mô tả OpenAPI, mã lỗi thống nhất, phân trang và mã truy vết.
- Giao tiếp đồng bộ chỉ khi cần phản hồi hoặc xác minh quyền; tác vụ nặng, lập chỉ mục và cập nhật phân tích dùng hàng đợi.
- Các sự kiện dự kiến: `MembershipRevoked`, `DocumentVersionReady`, `DocumentAccessRevoked`, `AssessmentSubmitted`, `AssessmentGraded`, `GradeRevised`, `PracticeCompleted`.
- Sự kiện thu hồi quyền hỗ trợ lan truyền thay đổi, **không thay thế kiểm tra quyền hiện hành**.
- Mọi dịch vụ phải có xác thực nội bộ, giới hạn thời gian chờ, kiểm thử tương thích API và chính sách thử lại phù hợp.

## 8. Bảo mật, quyền riêng tư và vận hành
Phân quyền theo vai trò và tài nguyên; ngăn truy cập chéo lớp; giới hạn tệp tải lên, xử lý tệp không tin cậy, bảo vệ bí mật và đường truyền, kiểm soát đường dẫn tải xuống, giới hạn truy vấn AI. Giảng viên và Admin không mặc định đọc hội thoại riêng tư. Yêu cầu xóa dữ liệu phải phân loại xóa/ẩn danh/giữ hợp lệ; thời hạn lưu giữ cụ thể cần phê duyệt. Nhật ký không mặc định lưu lời nhắc hay tài liệu nguyên văn. [F3–F7, K1–K6, O7–O8]

## 9. Triển khai và quan sát
[ĐỀ XUẤT] GitHub Actions kiểm thử và đóng gói từng dịch vụ; Docker để triển khai; Docker Compose cho môi trường ban đầu. Có kiểm thử đơn vị, tích hợp, hợp đồng, bảo mật và kiểm thử nhanh sau triển khai. Mỗi dịch vụ có ảnh đóng gói, kiểm tra sức khỏe và quy trình thay đổi cấu trúc dữ liệu riêng. Cần kế hoạch quay về phiên bản ứng dụng cũ và thay đổi cơ sở dữ liệu tương thích ngược. Docker Compose không tự bảo đảm tính sẵn sàng cao hay triển khai không gián đoạn.

Theo dõi tỷ lệ lỗi, p95, độ trễ hàng đợi, số tác vụ lỗi, xung đột nộp bài, từ chối truy cập, trích dẫn RAG, nhật ký có mã truy vết. Kiểm chứng sao lưu và phục hồi trước demo.

## 10. Ngăn xếp công nghệ và môi trường thực nghiệm — [ĐỀ XUẤT, CHƯA PHÊ DUYỆT]

**Toàn bộ nội dung mục này là phương án tham khảo dành cho nhóm 4 sinh viên, chưa phải quyết định công nghệ chính thức.** Chưa kiểm chứng chi phí, giới hạn dịch vụ hay năng lực đáp ứng TP-01. Chỉ kiến trúc Microservices là định hướng đã được nhóm lựa chọn.

### 10.1. Công nghệ đề xuất
| Thành phần | Công nghệ [ĐỀ XUẤT] | Ghi chú về chi phí và sử dụng |
|---|---|---|
| Giao diện Web | Next.js, TypeScript, Tailwind CSS | Mã nguồn mở; hosting có thể tính phí |
| Backend cho 5 dịch vụ | Python, FastAPI | Giảm số ngôn ngữ cần học; cần hạ tầng chạy API |
| Dữ liệu giao dịch | PostgreSQL; SQLAlchemy; Alembic | Tự host miễn phí; tách schema và tài khoản theo dịch vụ, không truy cập bảng chéo |
| Truy hồi vector | Qdrant tự host | Không mất phí dịch vụ phần mềm khi tự host; vẫn tốn tài nguyên máy |
| Lưu tệp | Kho lưu trữ tương thích S3; cân nhắc MinIO hoặc lựa chọn tương đương | Tự host hoặc dùng dịch vụ trả phí; cần kiểm tra giấy phép và phương án sao lưu |
| Tác vụ nền | Celery + Redis (phương án khởi đầu) | Không thay thế yêu cầu Transactional Outbox, chống trùng, đối soát; cần thử nghiệm độ bền hàng đợi trước khi dùng cho sự kiện quan trọng |
| AI/RAG | PyTorch, Sentence Transformers, embedding đa ngôn ngữ và LLM API | Thư viện có thể miễn phí; API thương mại/GPU có thể phát sinh phí; model cụ thể chưa chốt |
| Cổng API | Traefik Proxy | Dùng bản phù hợp để tự host; cần cấu hình HTTPS và xác thực đúng |
| Đóng gói | Docker Engine + Docker Compose trên Linux | Không cần Kubernetes ở giai đoạn đầu; Docker Desktop có điều kiện giấy phép riêng |
| CI/CD | GitHub Actions | Có hạn mức/điều kiện miễn phí; vượt hạn mức có thể tính phí |
| Kiểm thử | pytest, Playwright, k6 tự chạy | Tập trung chức năng, quyền truy cập, tải và lỗi phân tán |
| Quan sát | Health check và log có cấu trúc trước; cân nhắc Prometheus, Grafana, Loki khi cần | Tự host phần mềm có thể miễn phí nhưng tăng chi phí tài nguyên/vận hành |

**Lưu ý:** Redis và MinIO có các điều kiện cấp phép/phân phối tùy phiên bản; không mặc định mọi bản phát hành hoặc mọi cách dùng đều không có ràng buộc. Các mức miễn phí của nhà cung cấp API/hosting thay đổi theo thời gian và phải kiểm tra trước khi đăng ký.

### 10.2. Môi trường triển khai — [ĐỀ XUẤT]
1. **Development (phát triển):** máy cá nhân, Docker Compose, dữ liệu giả lập; khởi chạy các service cần thiết và PostgreSQL/Redis/Qdrant/kho tệp. Không sử dụng dữ liệu riêng tư thật trong fixture.
2. **Staging (tích hợp và thực nghiệm):** một VPS Linux có cấu hình cố định, Docker Compose, dữ liệu thử nghiệm và image được khóa phiên bản. **Cấu hình khởi đầu tham khảo:** 4 vCPU, 8 GB RAM, 80 GB SSD; không bảo đảm đạt TP-01 nếu chưa đo. Khi benchmark, ghi CPU/RAM, vùng mạng, DB, phiên bản model và lưu lượng.
3. **Demo (trình diễn):** môi trường có HTTPS, dữ liệu demo, bản triển khai đã qua kiểm thử; có thể chung máy Staging nhưng phải tách dữ liệu/cấu hình và tránh benchmark đồng thời.
4. **Máy tạo tải:** ưu tiên tách khỏi máy chạy hệ thống để tránh làm sai lệch số đo.
5. **Huấn luyện/embedding nặng:** dùng máy cá nhân, tài nguyên lab hoặc môi trường tính toán riêng khi cần; không mặc định chạy chung VPS demo.

### 10.3. Kế hoạch thực nghiệm — [ĐỀ XUẤT]
- **Chức năng:** pytest và Playwright kiểm tra luồng đăng nhập, phân quyền, tài liệu, nộp bài, chấm điểm và trợ giảng.
- **Hiệu năng:** k6 đo theo TP-01 và QAS-05; tách thời gian xử lý AI khỏi các API giao dịch.
- **Cô lập lỗi và toàn vẹn:** dừng AI/worker, gửi nộp bài trùng, phát lại sự kiện, thu hồi quyền, làm hỏng lập chỉ mục; đối chiếu QAS-01 đến QAS-04 và QAS-10.
- **Chất lượng RAG:** bộ câu hỏi được gán nhãn, đánh giá Recall@k (nếu có nhãn truy hồi), độ đúng trích dẫn, mức bám sát nguồn và từ chối khi thiếu căn cứ theo QAS-06.
- **Triển khai độc lập:** kiểm tra cập nhật AI mà không triển khai lại Learning theo QAS-08.

### 10.4. Ngân sách — [ƯỚC TÍNH, KHÔNG PHẢI BÁO GIÁ]
- Phát triển local: có thể không tốn phí thuê dịch vụ nếu không gọi API trả phí; vẫn có điện, internet và thiết bị.
- Khi thuê hạ tầng: dự trù sơ bộ **150.000–400.000 VNĐ/tháng cho VPS nhỏ**, **0–250.000 VNĐ/tháng cho LLM API**, và **0–50.000 VNĐ/tháng cho sao lưu bổ sung**; tổng tùy mức sử dụng, chưa gồm GPU, thuế và phí phát sinh.
- Không mua Kubernetes, Kafka cluster, GPU server riêng hoặc dịch vụ giám sát thương mại khi chưa có nhu cầu được đo đạc.
- [CHƯA CHỐT] Ngân sách tối đa, nhà cung cấp VPS, model embedding, LLM, cơ chế xác thực, kho tệp, hàng đợi sự kiện nghiệp vụ, RPO/RTO và chính sách lưu giữ.

## 11. Thuộc tính chất lượng
Tham chiếu [QUALITY_ATTRIBUTES.md](QUALITY_ATTRIBUTES.md). **P0:** Availability (sẵn sàng), Fault Isolation (cô lập lỗi), Data Integrity (toàn vẹn dữ liệu), Security & Privacy (bảo mật và riêng tư), Performance (hiệu năng), RAG Quality (chất lượng RAG). **P1:** Scalability (mở rộng), Deployability (triển khai độc lập), Modifiability (dễ thay đổi), Recoverability (phục hồi), Recommendation Quality (chất lượng gợi ý). Ngưỡng đo là mục tiêu dự kiến, chưa phải kết quả đạt được.

## 12. Rủi ro và vấn đề chưa chốt
- Đánh đổi giữa tính sẵn sàng và xác minh quyền: ưu tiên bảo mật, từ chối khi không xác minh được quyền.
- Cơ chế kích hoạt chỉ mục tài liệu, thu hồi quyền trong lúc AI đang sinh câu trả lời.
- Core là phụ thuộc quan trọng; cần giảm chuỗi gọi đồng bộ và xử lý sự cố quyền.
- Chi phí vận hành hàng đợi, sự kiện, nhật ký và các dịch vụ độc lập cho nhóm 4 người.
- Công nghệ và môi trường triển khai mới có **phương án đề xuất tại mục 10**, chưa được phê duyệt; mục tiêu phục hồi RPO/RTO và thời hạn lưu dữ liệu vẫn chưa chốt.
- Chủ sở hữu chuẩn của mục tiêu học tập, ánh xạ câu hỏi sang chủ đề và các tác vụ quản trị xuyên dịch vụ.

**Trạng thái cuối:** định hướng Microservices-first đã được nhóm lựa chọn; bộ công nghệ, môi trường triển khai và các ngưỡng đo vẫn ở mức **[ĐỀ XUẤT]**, chưa triển khai hoặc kiểm thử thực tế.
