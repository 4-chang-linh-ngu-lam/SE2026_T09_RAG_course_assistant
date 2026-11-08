# Prototype RAG từ bộ đề ToanMathWord (thử nghiệm)

> **Không phải AI Service.** Đây là thử nghiệm offline phục vụ thiết kế [TASK-018](../../tasks/TASK-018-ai-service-rag-tutor.md) (#23):
> kiểm chứng trích xuất công thức, chia chunk, truy hồi. Không chốt provider/vector store/API; mọi lựa chọn ở đây
> (bge-m3, BM25, RRF) chỉ là ứng viên chờ thiết kế được duyệt. Dữ liệu đề thi và kết quả sinh ra **không commit**
> (xem `.gitignore`); bộ dữ liệu mô tả ở [DATA_SGK_THCS_TOANMATH](../../docs/data/DATA_SGK_THCS_TOANMATH.md) và báo cáo `ToanMathWord` của người thu thập.

Nguồn: `DataSGK/ToanMathWord` (191 `.docx` + 24 `.doc`). Công thức trong file là **MathType (OLE)**, đọc trực tiếp dữ liệu MTEF → LaTeX, không dùng OCR.

## Chạy lại
```
pip install olefile rank_bm25 sentence-transformers
python docx2md.py <ToanMathWord> out_md          # .docx -> Markdown + LaTeX
# .doc: Word COM SaveAs2(FileFormat=16) -> doc_converted/, rồi docx2md.py doc_converted out_md_doc
python chunk.py out_md out_md_doc chunks.jsonl   # chia theo câu + metadata
python retrieve.py build                         # embeddings bge-m3 (CPU)
python retrieve.py "câu hỏi" 11                  # truy vấn, lọc lớp 11
python eval_mtef.py <ToanMathWord>               # kiểm tra chất lượng chuyển MathType
```

## Số liệu (2026-11-08)
- MathType → LaTeX: 21.622/21.657 công thức (99,8%) ở file `.docx`; khớp TeX gốc người soạn 99,64% (4.775 công thức có TeX gốc).
- File `.doc` (24 file): Word chuyển sang `.docx` làm **rỗng 270/2.767 công thức** (~10%) → thành `[CÔNG THỨC LỖI]`. Muốn lấy lại phải đọc ObjectPool trong `.doc` gốc.
- 472 ảnh dán thẳng (`w:pict`) + 395 ở file `.doc` → `[HÌNH]`, mất nội dung.
- 3.565 chunk (3.314 đề, 222 đáp án, 29 ma trận); 2.626 là chunk của mã đề chính (mỗi bộ đề giữ 1 mã).
- **Chỉ ~8% câu hỏi ghép được lời giải chi tiết** (44/114 bộ đề có file đáp án; nhiều file chỉ là bảng A/B/C/D).

## Đánh giá truy hồi (`eval_set.jsonl`, `python eval_retrieval.py`)
32 câu diễn đạt lại theo lời học sinh (đáp án = chunk gốc) + 8 câu ngoài dữ liệu, có lọc theo lớp.

| Cách | Recall@1 | Recall@5 | MRR |
|---|---|---|---|
| BM25 | 78% | 88% | 0,83 |
| bge-m3 | 72% | 94% | 0,82 |
| Kết hợp (RRF) | 75% | 91% | 0,82 |

Từ chối theo ngưỡng điểm bge-m3 top-1: 0,60 → giữ 91% câu có dữ liệu, từ chối đúng 75% câu ngoài dữ liệu; 0,65 → 81% / 100%. Ngưỡng đơn lẻ chưa đủ, cần thêm bước LLM tự kiểm tra căn cứ.
Bộ còn nhỏ (40 câu, do 1 người viết) — chỉ là tín hiệu ban đầu.

## Hệ quả cho Tutor
- Dữ liệu này hợp để **tìm đề/bài tương tự**, không đủ làm nguồn **lời giải từng bước**. Phần lý thuyết/định nghĩa/ví dụ mẫu vẫn cần SGK.
