# DeepDoc và RAG tài liệu

Mã nguồn nằm trong [services/rag](../../services/rag/README.md). Pipeline nhận tài liệu, trích xuất văn bản native hoặc OCR, tạo Canonical v2 có vị trí nguồn, chọn khối đủ điều kiện để chia đoạn và lập chỉ mục. Retrieval kiểm tra quyền hiện hành, đóng gói context theo ngân sách token và cung cấp đoạn trích đối chiếu được với nguồn.

| Thành phần | Vai trò |
| --- | --- |
| `idp/` | Trích xuất tài liệu, OCR, Canonical v2 và parser tương thích |
| `chunking/`, `indexing/`, `embedding/` | Chia đoạn, tạo bundle theo phiên bản và đọc embedding local |
| `search/`, `retrieval/`, `packing/` | Tìm kiếm, rerank, lọc quyền và lắp context |
| `citations/`, `generation/` | Trích dẫn theo span nguồn và đường ghép pipeline sinh câu trả lời |

## Chạy kiểm thử

Dùng Python 3.12 và chạy từ `services/rag` trên Windows. Các test trích xuất thật cần Poppler trên `PATH`. Test OCR cần Tesseract và traineddata phù hợp. C?c ca ??i chi?u parser tham chi?u ???c b? qua khi th? m?c ngu?n ngo?i repo v?ng m?t.

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-phase0.lock.txt -r requirements-rag-models.lock.txt
.venv/Scripts/python.exe -m pytest -q -ra -p no:cacheprovider
```

## Kết quả local ngày 18/11/2026

- Suite Windows đạt 489 pass, 2 skip và 2 XFAIL. Hai XFAIL ghi nhận giới hạn cũ về thứ tự đọc bảng và đơn vị tọa độ native/OCR.
- Trên bản Canonical của SGK Toán 10 đã trích xuất, cả `bài 1.2` và `bai 1.2` trả đúng đề ở hạng nhất và xác minh trích dẫn ở trang PDF 12. Lượt thử dùng SQLite/BM25.
- Bộ hồi quy model dùng fixture cho embedding, reranker và LLM, cùng một kiểm thử tokenizer thật trên file nhỏ. Các model thực cần artifact riêng. Web live vẫn có trạng thái chờ cho các tích hợp Document, Tutor và Learning.

Chunking hiện dùng `idp-text-chunking-7`. Tạo lại bundle và chỉ mục từ tài liệu nguồn khi chuyển từ phiên bản chunking cũ.
