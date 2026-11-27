# DeepDoc và RAG tài liệu

Mã nguồn nằm trong [services/rag](../../services/rag/README.md). Pipeline nhận tài liệu, chạy **Unified Adaptive Hybrid IDP** (`Native-first, CPU-first, GPU-on-demand`), tạo Canonical v1 (`idp-canonical-1` kèm contract/provenance tại `idp/canonical/` và cổng xuất bản fail-closed `idp/publish.py`), chiếu sang Markdown giữ nguyên công thức/bảng (`indexing/canonical_text.py`), chia đoạn bằng **`idp-text-chunking-10`** và lập chỉ mục. Retrieval kiểm tra quyền hiện hành hai lần (trước khi tạo tập ứng viên và trước khi trả về), chuẩn hóa chính tả tiếng Việt Layer A cho BM25, đóng gói ngữ cảnh theo ngân sách token với cận token chính xác và sinh trích dẫn kiểm chứng được theo span nguồn.

| Thành phần | Vai trò |
| --- | --- |
| `idp/`, `contracts/canonical.py` | Adaptive Hybrid IDP (`L0` native → `L1` Tesseract → `L2` PP-DocLayoutV3 → `L3` selective PaddleOCR-VL 1.6 → `L4` cross-read & fail-closed publish gate) |
| `chunking/`, `indexing/`, `embedding/` | Chia đoạn `idp-text-chunking-10`, chiếu Canonical sang Markdown (`canonical_text.py`), tạo bundle có phiên bản và đọc embedding ONNX local |
| `search/`, `retrieval/`, `packing/` | BM25 có trường bigram + chuẩn hóa chính tả tiếng Việt Layer A (và Layer B opt-in), hybrid fusion, rerank, lọc quyền và lắp ngữ cảnh lân cận tối ưu token |
| `citations/`, `generation/` | Trích dẫn theo span nguồn (bảo toàn dấu `;` trong tọa độ `(x; y)`), adapter `llama.cpp` và `OpenAICompatibleGenerator` (keep-alive pooling, multiline quote snapping) |

## Tài liệu chi tiết

- [So sánh và phân tích hiệu năng giữa 2 lần cập nhật RAG](rag-update-comparison.md)
- [Tổng quan thư viện & Adaptive Hybrid IDP](../../services/rag/README.md)
- [Chi tiết tầng Chunking (`idp-text-chunking-10`)](../../services/rag/chunking/README.md)
- [Chi tiết tầng Generation & Grounding](../../services/rag/generation/README.md)

## Chạy kiểm thử

Dùng Python 3.12 và chạy từ `services/rag` trên Windows. Các test trích xuất PDF thật cần Poppler trên `PATH`; test OCR cần Tesseract và `traineddata` tiếng Việt/Anh.

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-phase0.lock.txt -r requirements-rag-models.lock.txt
.venv/Scripts/python.exe -m pytest -q -ra -p no:cacheprovider
```

## Trạng thái cập nhật hiện tại

- **Kiểm thử tự động**: Bộ test `services/rag` trên nhánh `feature/lumi-web-deepdoc-rag` đạt **`295 passed, 0 failed`** (`28.38s`, Windows Python 3.12).
- **Chunking**: dùng **`idp-text-chunking-10`**. Các bundle tạo trước `idp-text-chunking-10` sẽ không qua bước kiểm tra và cần dựng lại từ tài liệu nguồn bằng `build_corpus`.
- **Retrieval & Hiệu năng**: trên bộ 100 câu hỏi chuẩn hóa `rag-100` (90 positive / 10 negative, BGE-M3 ONNX CPU trên 2 tài liệu `native` + `scan`), bản cập nhật mới nâng `quotable_support` từ `63 → 70` (single-doc) và `59 → 66` (class-wide), đồng thời giảm độ trễ median từ `120.05 ms → 95.25 ms` (single-doc) và `355.9 ms → 94.15 ms` (class-wide, nhanh hơn **3.78×**). Xem chi tiết số liệu đo thực tế tại [rag-update-comparison.md](rag-update-comparison.md).
- **Ghi chú tích hợp**: nhánh `feature/lumi-web-deepdoc-rag` chứa thư viện `services/rag` và tài liệu `docs/deepdoc`. Khi ghép với `services/ai` và `services/document`, giữ đồng bộ bản chiếu `canonical_to_markdown` và kiểm thử parity tương ứng.
