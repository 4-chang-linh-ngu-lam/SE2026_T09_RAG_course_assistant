# LUMI RAG — Tóm tắt khảo sát kỹ thuật

**Ngày khảo sát:** 2026-11-24
**Repository:** 4-chang-linh-ngu-lam/SE2026_T09_RAG_course_assistant
**Branch/HEAD:** codex/rag-technical-discovery / dc0671c36bf750ef914ac34d22e6ff2cf685287a
**Đồng bộ:** HEAD = origin/main, ahead/behind 0/0 trước khi tạo báo cáo.
**Trạng thái công việc:** chỉ tạo tài liệu discovery; không sửa application code, không commit, không push, không deploy.

## Kết luận điều hành

Mã RAG đã được merge vào monorepo và có pipeline Python offline để xử lý văn bản, tạo index cục bộ, truy hồi evidence và dựng câu trả lời có kiểm tra citation. Nó chưa phải HTTP service, chưa có conversation store, chưa gọi Core/Document/Learning thật và chưa chạy với model artifact Production.

Pipeline ingestion DeepDoc/IDP và pipeline text-RAG hiện mới nối ở mức các module riêng và local harness. Index chính nhận TextDocument dạng text/Markdown, ghi bundle/embedding vào filesystem; không có DocumentVersion/grant/tenant index contract. Retrieval cần caller truyền authorization callback, nhưng repository chưa cung cấp caller kết nối callback đó với Core và Document.

Production hiện không có AI Service/Document/Learning Cloud Run service. OpenAPI Core Production không có RAG/AI/Tutor route. Frontend live đánh dấu Tutor pending-contract. Vì vậy chưa thể kiểm thử RAG end-to-end trên Production.

## Trạng thái năng lực

| Năng lực | Trạng thái | Bằng chứng / giới hạn |
|---|---|---|
| File preflight và parser native/OCR | IMPLEMENTED, offline | idp.input, idp.documents, idp.ocr; entrypoint ingest_file. Không có Document Service hoặc upload API. |
| Canonical extraction / audit | IMPLEMENTED một phần | Current emitter là idp-canonical-1; DeepDoc docs mô tả Canonical v2 nhưng publisher v2 không có trong repository. |
| Text chunking | IMPLEMENTED, TESTED | chunk_text, validate_chunking; bundle version idp-text-chunking-7. Không phải API và không chứa school/class authorization. |
| Embedding/index | IMPLEMENTED, local artifact | ONNX adapters; NPY/JSON bundles trên filesystem. Không có managed vector DB/active-index lifecycle. |
| Hybrid retrieval | IMPLEMENTED, TESTED offline | Dense, BM25, structure, section, fusion; optional reranker. Authorization do caller cung cấp. |
| Grounded answer/citation | IMPLEMENTED, TESTED với fixture | Pipeline kiểm schema và quote/span; default không chứng nhận semantic grounding/correctness. |
| Real model execution | PARTIAL / UNVERIFIED | LlamaGenerator là client tới llama.cpp loopback với model path cục bộ; model/server chưa được cung cấp. |
| AI Service HTTP API / conversation persistence | NOT IMPLEMENTED | Không có services/ai, FastAPI router, endpoint, database/schema hay deployment service. |
| Core/Document/Learning integration | NOT IMPLEMENTED | Core access API tồn tại; Document và Learning service/API chưa có. RAG chỉ nhận callback authorize. |
| QAS-06 Production quality | UNVERIFIED | Không có bộ 100 câu được duyệt chạy với model thật và nguồn có grant thật. |

## Blocker quan trọng nhất

1. Không có API/service để Production gọi RAG.
2. Canonical v2 và text index chưa có adapter end-to-end; v2 path tham chiếu module idp.publish không có trong repo.
3. Chưa có hợp đồng Document để đọc version/content/active grants/revocation; source_acl trong Canonical chỉ là metadata đầu vào.
4. D6 cần Learning xác minh Assessment chính thức; chưa có Learning API nên Tutor phải fail closed.
5. Không có Production inference provider/model artifact; retrieval/generation CI dùng encoder và generator fixture.
6. Main RAG index lưu filesystem và nạp vectors vào RAM; chưa có store/version activation/delete/rollback phù hợp deployment nhiều instance.

## Bằng chứng kiểm thử

- GitHub Actions rag-tests trên PR #49: **144 passed, 2 skipped, 1 xfailed**, 2 warnings; chạy Python 3.12, không dùng model artifact thật.
- PR #46 ghi benchmark retrieval trên 48 câu/4 tài liệu và một lượt Gemini 12 câu; các kết quả này không phải QAS-06 acceptance và không phải test API Production.
- Local RAG tests **NOT RUN**: máy hiện có khoảng 0.50 GB RAM trống, Python mặc định 3.11.9 trong khi suite yêu cầu Python 3.12, không có pytest hoặc venv RAG. Không cài dependencies/model hoặc chạy Docker trong lượt khảo sát.
- AST parse tĩnh toàn bộ **183 file Python** dưới services/rag: 0 syntax errors. Đây không phải runtime test.
- Giữ nguyên hai file local chưa track có sẵn: docs/problem/ và stitch-rag-consistency.zip.

Xem chi tiết trong các tài liệu 01–09 cùng thư mục.
