# Prototype RAG từ bộ đề ToanMathWord (thử nghiệm)

> **Không phải AI Service.** Đây là thử nghiệm offline phục vụ thiết kế [TASK-018](../../tasks/TASK-018-ai-service-rag-tutor.md) (#23):
> kiểm chứng trích xuất công thức, chia chunk, truy hồi. Không chốt provider/vector store/API; mọi lựa chọn ở đây
> (bge-m3, BM25, RRF) chỉ là ứng viên chờ thiết kế được duyệt. Dữ liệu đề thi và kết quả sinh ra **không commit**
> (xem `.gitignore`); bộ dữ liệu mô tả ở [DATA_SGK_THCS_TOANMATH](../../docs/data/DATA_SGK_THCS_TOANMATH.md) và báo cáo `ToanMathWord` của người thu thập.

Thiết kế chi tiết, số liệu và các quyết định cần duyệt: [DESIGN.md](DESIGN.md).

Nguồn: `DataSGK/ToanMathWord` (191 `.docx` + 24 `.doc`). Công thức trong file là **MathType (OLE)**, đọc trực tiếp dữ liệu MTEF → LaTeX, không dùng OCR.




## Chạy lại
```
pip install olefile rank_bm25 sentence-transformers
python docx2md.py <ToanMathWord> out_md          # .docx -> Markdown + LaTeX
# .doc: Word COM SaveAs2(FileFormat=16) -> doc_converted/, rồi docx2md.py doc_converted out_md_doc
python chunk.py out_md out_md_doc chunks.jsonl   # chia theo câu + metadata
python retrieve.py build                         # embeddings bge-m3 (CPU)
python retrieve.py "câu hỏi" 11                  # truy vấn, lọc lớp 11
python answer.py "câu hỏi" --lop 10 --mode step  # hỏi đáp có trích dẫn (cần OPENAI_API_KEY)
python eval_mtef.py <ToanMathWord>               # kiểm tra chất lượng chuyển MathType
python eval_answers.py --mode quick               # đánh giá bước trả lời (gọi API thật, ~40 câu)
```

## Số liệu (2026-11-08)
- MathType → LaTeX: 21.622/21.657 công thức (99,8%) ở file `.docx`; khớp TeX gốc người soạn 99,62% (4.775 công thức có TeX gốc).
- File `.doc` (24 file): Word chuyển sang `.docx` làm **rỗng 270/2.767 công thức** (~10%) → thành `[CÔNG THỨC LỖI]`. Muốn lấy lại phải đọc ObjectPool trong `.doc` gốc.
- 472 ảnh dán thẳng (`w:pict`) + 395 ở file `.doc` → `[HÌNH]`, mất nội dung.
- 3.565 chunk (3.314 đề, 222 đáp án, 29 ma trận); 2.626 là chunk của mã đề chính (mỗi bộ đề giữ 1 mã).
- Ghép căn cứ đáp án vào câu (chỉ khi khớp mã đề): 156 lời giải chữ + 294 đáp án trắc nghiệm đọc từ bảng (`answer_keys.py`, 4 kiểu bảng)
  = **450/2.375 câu (19%)**. Trước khi bắt khớp mã đề có 41 lời giải bị ghép nhầm sang mã đề khác.

## Đánh giá truy hồi (`eval_set.jsonl`, `python eval_retrieval.py`)
32 câu diễn đạt lại theo lời học sinh (đáp án = chunk gốc) + 8 câu ngoài dữ liệu, có lọc theo lớp.

| Cách | Recall@1 | Recall@5 | MRR |
|---|---|---|---|
| BM25 | 78% | 88% | 0,83 |
| bge-m3 | 72% | 94% | 0,82 |
| Kết hợp (RRF) | 75% | 91% | 0,82 |
| RRF + reranker `bge-reranker-v2-m3` (top 20) | **84%** | **97%** | **0,89** |

Từ chối theo ngưỡng điểm bge-m3 top-1: 0,60 → giữ 91% câu có dữ liệu, từ chối đúng 75% câu ngoài dữ liệu; 0,65 → 81% / 100%. Ngưỡng đơn lẻ chưa đủ, cần thêm bước LLM tự kiểm tra căn cứ.
Điểm reranker (0–1) tách tốt hơn: ngưỡng 0,3 → giữ 97%, từ chối 62%; 0,9 → 78% / 100%.
`answer.py` dùng ngưỡng 0,3 để chặn sớm, phần còn lại do LLM trả `KHONG_DU_CAN_CU`.
Bộ còn nhỏ (40 câu, do 1 người viết) — chỉ là tín hiệu ban đầu.

## Hệ quả cho Tutor
- Dữ liệu này hợp để **tìm đề/bài tương tự**, không đủ làm nguồn **lời giải từng bước**. Phần lý thuyết/định nghĩa/ví dụ mẫu vẫn cần SGK.

## Sinh câu trả lời (`answer.py`)
- LLM mặc định `gpt-4o-mini` (đổi qua `OPENAI_MODEL`); key lấy từ `OPENAI_API_KEY`, không ghi vào code.
- 2 chế độ: `quick` (QUICK_QA) và `step` (STEP_BY_STEP).
- Mỗi nguồn gắn nhãn `CÓ LỜI GIẢI` / `CHỈ CÓ ĐỀ`; cấm nêu đáp án từ nguồn chỉ có đề.
- Kiểm tra theo thứ tự (fail closed):
  1. Điểm reranker < ngưỡng → `refused`.
  2. LLM báo `KHONG_DU_CAN_CU` → `refused`; trích nguồn không tồn tại → `refused`.
  3. Không có trích dẫn, hoặc **mọi nguồn được trích chỉ có đề** (luật cứng, không dựa LLM) → `similar_only`: chỉ liệt kê bài tương tự.
  4. LLM thứ hai (nhiệt độ 0, JSON) đối chiếu từng khẳng định với nguồn; có khẳng định không căn cứ → `similar_only`.
  5. Nguồn có lời giải được trích phải có điểm reranker ≥ 0,5 (gần như cùng bài) → nếu không: `similar_only`.
- LLM trả mã `KHONG_LIEN_QUAN` (→ `refused`) hoặc `CHI_CO_BAI_TUONG_TU` (→ `similar_only`).
- Dò trích dẫn bỏ qua phần công thức (`\sqrt[2022]{}` từng bị hiểu là trích dẫn [2022]).

### Đánh giá bước trả lời (`eval_answers.py`, gpt-4o-mini, 2026-11-09, 40 câu)
| Chỉ số | Kết quả |
|---|---|
| Hành vi đúng tổng | **37/40 (92%)** |
| — cần trả lời (có căn cứ) | 6/8 |
| — cần chỉ gợi ý bài tương tự | 23/24 |
| — cần từ chối (ngoài dữ liệu) | 8/8 |
| Trích dẫn chứa chunk đúng | 29/32 (91%) |
| Câu được trả lời mà nội dung sai (soát tay 7 câu) | 0 |
| Token/câu | ~2.000 vào, ~80 ra |

3 ca lệch: 2 ca quá thận trọng (gợi ý thay vì trả lời), 1 ca trả lời bài "nhận biết BPT bậc nhất hai ẩn" dựa trên đáp án của câu tương tự.
Lỗi đã tìm và sửa qua đánh giá: lời giải ghép nhầm mã đề (dẫn tới phương sai sai công thức $rac{1}{n-1}$),
LLM kiểm tra chấp nhận lời giải của bài khác làm căn cứ → thêm luật điểm ≥ 0,5.
Bộ 40 câu do 1 người viết, chưa đủ cho QAS-06 (≥100 câu).
- Lưu ý dữ liệu: câu hỏi + đoạn đề được gửi sang OpenAI. Với chat thật của học sinh (riêng tư, E5/F3) cần nhóm duyệt provider/điều khoản trước.
