# Full pipeline tài liệu trên Colab

Mở **deepdoc_full_rag_colab.ipynb**, chọn GPU, sửa `RAG_DRIVE`, `INPUT_DRIVE` (FILE PDF) và `QUERY`, rồi Run all. Đồng bộ cả thư mục `colab` và code `idp/pdf/service.py` mới lên Drive trước khi mở notebook.

Đường thực thi:

1. `DeepDocService(engine=unified, canonical_version=2)` và native engine tích hợp của repo.
2. Router giữ text native tốt; vùng/trang cần OCR chạy Tesseract `vie+eng`.
3. Cùng ImageFrame đi qua PP-StructureV3 GPU cho table/layout và `PP-FormulaNet_plus-S` cho công thức. Một worker GPU giữ model qua các trang, không dùng OCR-VL. Core và Paddle có venv Linux riêng.
4. StructuredAcquisitionResult được đưa vào merger/finalizer hiện có, giữ raw/producer/model weights, không thay native candidates.
5. Projector Canonical v2 và PublishPolicy hiện có. Model table/math chưa xác minh bị giữ lại để review, không tự publish. Không lấy layout score làm recognition confidence.
6. `iter_retrievable_blocks` → chunker hiện có → SQLite LocalRagIndex → FieldedBM25 → resolve_citation.

Index/retrieval là harness local đã có ở Phase 4. Notebook cấp local-owner grant chỉ cho đúng source/version đang được người dùng nhập, không suy ra quyền lớp học và không nối permission provider production. Chưa có vector embeddings hoặc LLM sinh câu trả lời. Không dựng service web/Core trên Colab.

Kết quả ở `MyDrive/deepdoc-full-rag-results/<attempt>/`: `deepdoc/extraction.json`, `deepdoc/canonical.json`, routes/publication/run reports, `canonical-v1-filtered.json`, `chunks.json`, `rag.sqlite3`, `retrieval.json`, `summary.json`, log và package freeze của cả hai môi trường. Cell query cuối dùng lại index mà không OCR lại.

Full service finalize ở mức document, chưa có resume từng trang. Các attempt không ghi đè nhau. Notebook raw OCR-VL cũ giữ nguyên cho người cần kiểm chứng riêng backend đó.

## Kiểm chứng

- 111 tests PASS trong Docker core: ba bài full-pipeline mới và toàn bộ tests Phase 3/4. Native PDF không gọi model; scan dùng Tesseract thật, typed structured response giả lập; model failure không tạo index; formula chưa xác minh không lọt vào chunks.
- CLI/lint và cú pháp notebook/query subprocess đã kiểm tra local.
- Đã đối chiếu constructor PPStructureV3 với package PaddleOCR 3.7.0 đã cài.
- Chưa chạy GPU PP-Structure trong Colab từ phiên local này; các test giả lập không phải bằng chứng inference model. Không tuyên bố tốc độ, chất lượng nhận dạng hay Phase 4 COMPLETE.

## Resource contract

`DeepDocConfig.max_gpu_calls` là ngân sách opt-in mới; mặc định 0. Colab truyền số hữu hạn theo số trang, transport reserve/settle GPU trên cùng ResourceLedger; CPU admission của BackendAcquirer và ngân sách render hiện có vẫn hoạt động. Acquisition deadline bao gồm thời gian GPU load/inference. Worker cùng process group với core để Stop/timeout từ notebook dừng cả hai; khi hết thời hạn request, core dừng riêng worker.

Giới hạn admission hiện có: 256 MiB nguồn, 2000 trang, 256 triệu pixel render tổng. Không tự bỏ trang hoặc nới policy khi vượt giới hạn. Table/math output chưa được xác minh có thể làm số chunk ít hơn raw content; phải kiểm tra publication report, không tự cấp eligibility.

Nguồn: [PP-StructureV3](https://www.paddleocr.ai/v3.3.1/en/version3.x/pipeline_usage/PP-StructureV3.html), [FormulaNet](https://www.paddleocr.ai/v3.5.0/en/version3.x/pipeline_usage/formula_recognition.html).
