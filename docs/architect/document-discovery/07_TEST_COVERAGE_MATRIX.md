# DOC-00.7 — Ma trận coverage 48 Acceptance Criteria

**Nguồn:** DOC-T06 trong docs/architect/rag-design/00_DESIGN_STATUS.md tại HEAD sau pull c7f56c722f421bf1df17f5a82f26a78682eb82be.

**Kết luận:** chưa có Document service nên chưa có AC nào được chứng minh ở mức tích hợp. Một vài unit test Core/RAG/Web có thể kiểm tra mảnh logic gần đó, nhưng không thay thế các AC service-to-service.

| AC | Hành vi cần chứng minh | Evidence hiện tại / coverage |
|---|---|---|
| 01 | Upload file hợp lệ | Web validation và RAG input parser là thành phần riêng; Document endpoint/storage chưa có. |
| 02 | Chặn giới hạn dung lượng | RAG có giới hạn độc lập 512 MiB; chưa là Document upload policy 50 MB. |
| 03 | Từ chối file không hợp lệ | Parser RAG có fail-closed input checks; không có server upload contract Document. |
| 04 | Version/file bền qua restart | Không có Document DB + persistent file volume. |
| 05 | Dọn file mồ côi | Không có Document reconciliation/cleanup job. |
| 06 | Tạo version đồng thời không trùng | Không có Document transaction/constraint. |
| 07 | Phát hiện checksum mismatch | RAG có source checksum trong pipeline; thiếu Document upload/download handoff test. |
| 08 | AI chỉ trả nhận job sau khi lưu bền vững | Không có AI HTTP API hoặc durable job DB. |
| 09 | Lost response được deduplicated | Không có Document–AI idempotency integration. |
| 10 | Cùng key khác payload trả 409 | Chưa có API/job contract test. |
| 11 | Worker recover sau restart | RAG worker local tồn tại; chưa chứng minh Document/AI durable execution. |
| 12 | Lease fencing ngăn worker cũ | Không có Document PostgreSQL lease/fencing. |
| 13 | Retry giữ lịch sử | Không có Document job history. |
| 14 | Poll timeout không đánh job FAILED | Không có Document poller/status state. |
| 15 | AI restart sau 202 | Không có AI REST service/contract test. |
| 16 | Activate V1 khi index sẵn sàng | Không có Document active version pointer. |
| 17 | Giữ V1 trong khi V2 đang xử lý | Không có Document version activation test. |
| 18 | Giữ V1 khi V2 thất bại | Không có backend version/job lifecycle. |
| 19 | Activate V2 sau readiness | Không có Document/AI index readiness handshake. |
| 20 | Job cũ không ghi đè active version mới | Không có stale-result guard. |
| 21 | Delete trong lúc ingest không hồi sinh nguồn | Không có deletion/job fencing integration. |
| 22 | Job SUCCEEDED nhưng index chưa ready không được activate | Không có index_ready contract. |
| 23 | Outsider bị từ chối | Core có class authorization; không có grant-aware Document route. |
| 24 | Spoof owner bị từ chối | Chưa có Document API lấy owner từ authenticated principal. |
| 25 | User JWT không gọi internal API | Core internal check yêu cầu service key; không có contract test Service JWT hiện hành. |
| 26 | Service JWT hết hạn bị từ chối | Service JWT chưa triển khai theo DOC-T04. |
| 27 | Sai audience/scope bị từ chối | DOC-T04 target chưa có issuer/audience/scope test. |
| 28 | Không tải file ngoài job scope | Không có internal file API. |
| 29 | Core down thì fail closed | Core check có lỗi dependency handling; không có Document caller E2E. |
| 30 | Document scope down thì fail closed | Không có Document scope API hoặc AI consumer. |
| 31 | Revoke trước retrieval ngăn truy vấn | Không có Document grant/index integration. |
| 32 | Revoke trước response loại nguồn khỏi trả lời | RAG callback có recheck tại engine, nhưng không được nối grant API. |
| 33 | Spoof document ID bị từ chối | Không có Document ownership/grant API test. |
| 34 | Internal API không public qua gateway | Không có Document/AI deployment/gateway routing để kiểm tra. |
| 35 | Upload vẫn hoạt động khi AI offline | Không có Document upload API; khả năng storage độc lập chưa được triển khai. |
| 36 | Download vẫn hoạt động khi AI offline | Không có Document streaming API. |
| 37 | Circuit breaker trả 503 đúng ngữ nghĩa | Không có Document→AI client/circuit breaker. |
| 38 | 429 tôn trọng Retry-After | Không có internal AI integration test. |
| 39 | Bounded concurrency | Không có Document/AI distributed worker limits. |
| 40 | Document restart recover jobs | Không có Document persistent job store. |
| 41 | Job lâu phát cảnh báo một lần | Không có Document monitoring/alert. |
| 42 | Job lâu không bị đánh thất bại giả | Không có state/polling policy. |
| 43 | PDF thật được index qua các service | Có local RAG PDF/parsing harness; thiếu Document-owned source, AI HTTP service và real integrated evidence. |
| 44 | QA chỉ trong scope được phép | Engine callback-level behavior có test; thiếu Core + Document grant end-to-end. |
| 45 | Citation trỏ đúng version | Harness có source/version/checksum identity; chưa có Document version DTO/index activation journey. |
| 46 | Thay version không dùng nhầm index | Chưa có tích hợp Document active pointer với index readiness. |
| 47 | Grant revoke có hiệu lực | Core class check không tương đương Document grant; chưa có cross-service test. |
| 48 | Deletion cleanup hoàn tất | Không có production index delete/file cleanup hoặc approved retention test. |

## Test evidence hiện có

- Git tree tại 680beaf (PR #49 merge), 2d97551, dc0671c và c7f56c7 đều có 15 file test_*.py dưới services/rag. Không có RAG test tree changes trong 2d97551..c7f56c7. Chúng cover parser/retrieval/generation fixtures, không chứng minh Document API hoặc real cross-service authorization.
- RAG discovery cũ ghi CI PR #49: 144 passed, 2 skipped, 1 xfailed, 2 warnings trên Python 3.12.16; đây là report cũ, không chạy lại trong R1. Đây là số test outcomes theo report, không phải file count. System Integration ghi 144 acceptance criteria kế hoạch (120 service + 24 system), là metric khác. Nguồn số 21 RAG test files chưa xác minh.
- services/core/tests có 33 file test_*.py; apps/web/tests có 40 test files. Chúng chủ yếu xác minh Core/Web riêng lẻ.
- .github/workflows/core-ci.yml hiện chạy RAG, Core/PostgreSQL, Web build và Compose smoke. Không có test Document, mock AI boundary hoặc mixed-service AC gate.

## Kiểm tra trong lượt DOC-00

Đã chạy các lệnh đọc Git status/ref/diff, kiểm kê file, tìm route/migration/adapter và đếm file test. Đây đều là kiểm tra read-only. Không chạy pytest, npm, Docker Compose, migration, live API hoặc benchmark: Python 3.11.9, pytest không cài và RAM trống khoảng 1.21 GB. Vì vậy chưa có kết quả test mới để gán cho DOC-00.

## System acceptance ngoài DOC-T06

CORE-T08/C-AC17 và SYS-07/S-AC14 yêu cầu distributed account deletion completion; NTF-T03 yêu cầu durable event inbox. Chưa có Document receiver/local cleanup/AI index handshake/per-target completion E2E. Thêm các trường hợp này vào DOC-12/SYS-05 khi contracts được duyệt; không gộp vào 48 DOC AC gốc.
