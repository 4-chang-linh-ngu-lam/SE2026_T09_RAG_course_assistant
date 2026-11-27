# Phân tích thay đổi và hiệu năng giữa 2 lần cập nhật `services/rag`

Tài liệu này tổng hợp đầy đủ khác biệt kiến trúc, chất lượng truy hồi, độ trễ hệ thống và kiểm chứng End-to-End giữa:
- **Bản trên GitHub (`origin/feature/lumi-web-deepdoc-rag` @ `0c059e5`)**: IDP tách lớp cũ + `idp-text-chunking-7` + `LocalRagIndex` (SQLite/BM25).
- **Lần cập nhật 1 (`4fac26a`, local `feature/lumi-web-deepdoc-rag`)**: nâng chunking lên `idp-text-chunking-8` (`14` file thay đổi so với `0c059e5`, chưa push lên GitHub).
- **Lần cập nhật 2 (hiện tại, `7e468d8`)**: **Unified Adaptive Hybrid IDP** + `canonical_text.py` + **`idp-text-chunking-10`** + BM25 bigram & chuẩn hóa chính tả tiếng Việt Layer A + `OpenAICompatibleGenerator` + tối ưu hiệu năng (`184` file thay đổi trong `services/rag` so với `0c059e5`).

Mọi số liệu đều lấy trực tiếp từ các lượt chạy thực tế trên `rag-100` (BGE-M3 ONNX CPU và API LLM thật); không suy đoán hoặc tự đặt KPI.

---

## 0. So sánh nhanh với bản đang có trên GitHub (`0c059e5`)

Theo kết quả đo thực tế của pipeline cũ (`demo-ui/local-live/idp-restored-rag/rag-100/summary.json`) trên cùng bộ 100 câu hỏi `rag-100`:

| Chỉ số trên `rag-100` (90 câu positive) | Bản trên GitHub (`0c059e5`, v7 + IDP cũ) | Bản mới nhất (`7e468d8`, v10 + Adaptive IDP + BGE-M3) | Chênh lệch |
| --- | :---: | :---: | :---: |
| Trang publish được (`native` / `scan`) | `13 / 141` (`116` chunks) · `0 / 106` (`0` chunks) | Dùng toàn bộ trang hợp lệ (`native` 329 · `scan` 271 chunks) | Mở khóa toàn bộ tài liệu `scan` |
| `gold_page` tìm thấy (`@5` / packed) | `27 / 90` (`30.0%`) | **`85 / 90` (`94.4%` single)** / **`82 / 90` (`91.1%` class)** | **`+58` câu (+64.4%)** |
| Hỗ trợ bằng chứng (`evidence@5` / `quotable_support`) | `21 / 90` (`23.3%`) | **`70 / 90` (`77.8%` single)** / **`66 / 90` (`73.3%` class)** | **`+49` câu (+54.4%)** |
| Nhóm `scan` (`40` câu) | `0 / 40` (do `0` trang scan được publish) | **`39 / 40` (`gold_page_packed`)** · `30 / 40` (`quotable_support`) | **`0 → 39 / 40`** |
| Generation & Orthography | Chỉ `LlamaGenerator`, chưa có Layer A | Thêm `OpenAICompatibleGenerator` keep-alive, multiline quote snap, Layer A tiếng Việt | Hoàn chỉnh cho production |

### 0.1. Chênh lệch & Cân đối giữa Hiệu năng và Độ chính xác

| Trục so sánh | Chênh lệch Hiệu năng (Tốc độ / Chi phí) | Chênh lệch Độ chính xác (Chất lượng truy hồi & trả lời) | Kết luận cân đối (Trade-off) |
| --- | --- | --- | --- |
| **Bản GitHub (`0c059e5`, v7) → Bản mới (`7e468d8`, v10 + perf)** | Từ SQLite/BM25 nhẹ trên `116` chunk sang Hybrid BM25 + BGE-M3 ONNX CPU trên `600` chunk: truy vấn chỉ tốn **`94–95 ms`** median (`p95 148–207 ms`). | `gold_page` tăng **`27 → 85 / 90`** (`+64.4%`); hỗ trợ bằng chứng tăng **`21 → 70 / 90`** (`+54.4%`); tài liệu `scan` từ **`0/40 → 39/40`**. | Đổi ~`95 ms` CPU để mở khóa toàn bộ tài liệu scan và nâng độ phủ bằng chứng gấp **3.3×**. |
| **Update 1 (`4fac26a`, v8) → Update 2 (`7e468d8`, v10 + perf)** | Single-doc giảm **`120.05 → 95.25 ms`** (**-20.7%**); Class-wide giảm **`355.90 → 94.15 ms`** (**nhanh hơn 3.78×**). Thời gian build 1 lần lúc ingest tăng nhẹ `+11.4%` (`186.6s → 207.8s` native; `158.3s → 166.8s` scan). | Single-doc: `gold_page 82→85`, `packed 71→74`, `quotable 63→70` (**+7 câu**); Class-wide: `gold_page 77→82`, `packed 67→69`, `quotable 59→66` (**+7 câu**). | **Thắng cả hai chiều** lúc truy vấn (vừa chính xác hơn vừa nhanh hơn); chỉ trả thêm ~21s một lần duy nhất khi build index. |
| **Update 2 trước tối ưu (`2b`) → sau tối ưu (`2c`)** | Single-doc giảm **`1,163.80 → 95.25 ms`** (**12.2×**); Class-wide giảm **`2,109.05 → 94.15 ms`** (**22.4×**); `fit_quotable_evidence` giảm **`1,062.8 → 25.6 ms`** (**41.5×**). | **Không đánh đổi độ chính xác**: `packed_support` (`74/90` single, `69/90` class) và `quotable_support` (`70/90` single, `66/90` class) **giữ nguyên 100%**; kiểm chứng tương đương `0/100` sai lệch. | Tối ưu thuần thuật toán (exact-safe token bounds + span validation O(1) + O(N) quote fit), **không hy sinh chất lượng**. |
| **Chính tả tiếng Việt: Layer A vs Layer B** | Layer A có `@lru_cache(8192)`, overhead không đáng kể; Layer B thêm 1 lượt chấm điểm lexical folded. | Layer A bật mặc định giúp `19/19` biến thể dấu/i-y khớp đúng và `0` va chạm; Layer B (`0.25`) tăng thêm `85→86` / `74→76` nhưng gây `377/1,916` nhóm va chạm đồng âm trên SGK. | Bật mặc định **Layer A** (an toàn tuyệt đối); giữ **Layer B opt-in (`0.0`)** để tránh nhiễu precision. |
| **E2E LLM: Fix quote/context & chọn model** | Holdout giảm median `3,199.2 → 2,429.1 ms` (lượt 1) + keep-alive bỏ TLS handshake lặp. Chi phí model nhẹ `deepseek-v4.1-flash-1017` (`deepinfra/fp8`) rất thấp nhưng `llm_ms ~3.1s`. | Holdout 19 câu tăng **`10/14 → 13/14` (`92.9%`)**, `0/5` negative hallucination. Toàn bộ `rag-100` với model giá rẻ đạt `64/90` (`concept 88.2%`), `2/10` negative. | Nút cổ chai độ trễ E2E hiện nằm ở **LLM API (~3s)** chứ không còn ở RAG (`~0.1s`); chọn model cân bằng giữa chi phí và độ chặt refusal. |

---

## 1. Phạm vi 2 lần cập nhật

| Hạng mục | Lần cập nhật 1 (`0c059e5` → `4fac26a`) | Lần cập nhật 2 (hiện tại) |
| --- | --- | --- |
| **IDP Pipeline** | DeepDoc OCR tách lớp cũ (`idp/ocr/*`, `idp/structured/*`, `idp/orchestration/*`) | **Unified Adaptive Hybrid IDP** (`idp/pipeline/*`, `idp/backends/*`, `idp/evidence/*`): Native-first → CPU-first → GPU-on-demand (`L0`–`L4`), publish gate fail-closed |
| **Canonical Projection** | Chuyển thẳng `text` phẳng (công thức mất delimiter, bảng bị gộp 1 dòng) | `indexing/canonical_text.py`: giữ display LaTeX (`$$`, `\[`, `\begin{align}`), bảng GFM/HTML→GFM, heading level và `block_id`/`bbox` |
| **Chunking** | `idp-text-chunking-7` (`0c059e5`) → `idp-text-chunking-8` (`4fac26a`, `native` 293 / `scan` 258 chunks) | **`idp-text-chunking-10`** (`native` 329 / `scan` 271 chunks): cô lập unclosed math/code fence, tránh fragmentation khi paragraph-snap, `validator.py` & `cli.py` tách riêng |
| **Lexical & Orthography** | BM25 từ đơn cơ bản + accent fallback toàn cục | BM25 có **body bigram field**, **Layer A `normalize_vi_orthography`** (chuẩn hóa vị trí dấu NFD + `_IY_MAP` không va chạm, `@lru_cache(8192)`), **Layer B `lexical_folded_boost`** opt-in (mặc định `0.0`), smart recovery |
| **Reranker & Packing** | `max_tokens` giới hạn thấp hơn; `neighbor_context` chạy lại BPE tokenizer đầy đủ cho từng lượt thử ghép hàng xóm | Reranker `max_tokens` tới `8192`, continuation packing tốt hơn; **`TextRetriever` lưu sẵn `_search_text_tokens`** và `neighbor_context` dùng **cận cộng token chính xác** cho `local_huggingface_tokenizer` |
| **Citations & Quotes** | Tách câu theo `;` cắt nhầm tọa độ `(x; y)`; validate span lặp lại theo từng snippet | `skip_paren_semicolon=True` bảo toàn tọa độ toán học; **`_validate_record_spans`** kiểm span 1 lần/item + **`_span_covers_range`** O(1) |
| **Generation Adapter** | Chỉ có `LlamaGenerator` cục bộ | Bổ sung **`OpenAICompatibleGenerator`** (`generation/openai_compatible.py`) với **`httpx.Client` keep-alive pooling**, **multiline quote snapping an toàn** (`len >= 16` + coverage `>= 75%`) và `tasks/qa/expand.py` |

> **Lưu ý về cấu trúc nhánh**: Trên nhánh `feature/lumi-web-deepdoc-rag`, chỉ có thư mục `services/core` và `services/rag`. Các tối ưu phía consumer `services/ai` (incremental O(N) `fit_quotable_evidence`, LRU query vector cache 256 mục, và `ThreadPoolExecutor` truy hồi song song đa tài liệu) được ghi nhận riêng ở mục 3 để thấy rõ tác động tổng thể trên pipeline Tutor đầy đủ.

---

## 2. Chất lượng & Độ trễ Retrieval trên `rag-100`

Bộ đánh giá `rag-100` gồm **100 câu hỏi** (`90` câu có đáp án trong tài liệu + `10` câu negative ngoài tài liệu) chạy trên 2 tài liệu thực tế đã trích xuất Canonical (`native`: Giáo trình Phương trình vi phân — 50 pos / 5 neg; `scan`: SGK Toán 10 VL OCR — 40 pos / 5 neg), dùng **BGE-M3 ONNX trên CPU**.

Để thấy rõ tác động của **tính năng** so với **tối ưu hiệu năng**, bảng dưới tách thêm mốc trung gian của Lần cập nhật 2 trước khi tối ưu hiệu năng:

- **Update 1 (`4fac26a`, v8)**: Baseline trên `feature/lumi-web-deepdoc-rag` (`indexed-vl/summary.json`).
- **Update 2a (v10 + retrieval fixes, trước `fit_quotable_evidence` O(N²))**: Đo riêng cải thiện chất lượng chunking v10 + search fixes (`out/summary.json`).
- **Update 2b (v10 + Layer A + `fit_quotable_evidence` O(N²), trước tối ưu perf)**: Khi bổ sung chọn lọc quote trước lúc gọi LLM nhưng chưa tối ưu thuật toán (`out_layer_a/summary.json`).
- **Update 2c (bản cuối sau toàn bộ tối ưu perf)**: Trạng thái hiện tại (`out_perf/summary.json`).

### 2.1. Tổng hợp toàn bộ `rag-100` (90 câu positive / 10 câu negative)

| Chế độ | Phiên bản | `gold_page_packed` | `packed_support` | `quotable_support` | `median_ms` | `p95_ms` | So với Update 1 |
| --- | --- | :---: | :---: | :---: | :---: | :---: | --- |
| **`indexed_single`** (1 tài liệu) | Update 1 (v8) | 82 / 90 | 71 / 90 | 63 / 90 | `120.05 ms` | `163.9 ms` | Baseline |
| | Update 2a (v10 + search) | 85 / 90 | 74 / 90 | 70 / 90 | `141.65 ms` | `221.5 ms` | +3 / +3 / +7 chất lượng; +18.0% trễ |
| | Update 2b (+ quote fit, pre-perf) | 85 / 90 | 74 / 90 | 70 / 90 | `1,163.80 ms` | `1,546.5 ms` | Nghẽn O(N²) quote fit + BPE |
| | **Update 2c (bản cuối + perf)** | **85 / 90** | **74 / 90** | **70 / 90** | **`95.25 ms`** | **`148.3 ms`** | **+3 / +3 / +7 chất lượng; nhanh hơn 20.7% median (12.2× vs 2b)** |
| **`indexed_class`** (cả 2 tài liệu) | Update 1 (v8) | 77 / 90 | 67 / 90 | 59 / 90 | `355.90 ms` | `449.4 ms` | Baseline |
| | Update 2a (v10 + search) | 83 / 90 | 69 / 90 | 66 / 90 | `382.80 ms` | `570.0 ms` | +6 / +2 / +7 chất lượng; +7.6% trễ |
| | Update 2b (+ quote fit, pre-perf) | 83 / 90 | 69 / 90 | 66 / 90 | `2,109.05 ms` | `3,056.2 ms` | Nghẽn O(N²) + chạy tuần tự 2 doc |
| | **Update 2c (bản cuối + perf)** | **82 / 90**\* | **69 / 90** | **66 / 90** | **`94.15 ms`** | **`206.8 ms`** | **+5 / +2 / +7 chất lượng; nhanh hơn 3.78× median (22.4× vs 2b)** |

*\*Ghi chú `83 → 82` ở `indexed_class`: chỉ có 1 câu (`q018`) rơi trang gold khỏi cửa sổ đóng gói khi `skip_paren_semicolon=True` giữ một câu chứa tọa độ dài hơn ở chunk liền trước; `q018` vốn đã có `packed_support=False` ở cả 2b và 2c nên `packed_support` (`69/90`) và `quotable_support` (`66/90`) không hề suy giảm.*

### 2.2. Phân tách theo nguồn tài liệu (`native` vs `scan` OCR)

| Tập con | Chế độ | Update 1 (v8) `gold / packed / quotable` | Update 2c (v10 + perf) `gold / packed / quotable` | Độ trễ median (U1 → U2c) |
| --- | --- | :---: | :---: | :---: |
| **`native`** (50 pos) | `indexed_single` | 45 / 37 / 33 | **46 / 40 / 40** (`+1 / +3 / +7`) | `116.6 ms → 95.6 ms` (**-18.0%**) |
| **`native`** (50 pos) | `indexed_class` | 43 / 37 / 33 | **45 / 39 / 39** (`+2 / +2 / +6`) | `361.0 ms → 104.0 ms` (**3.47×**) |
| **`scan`** (40 pos) | `indexed_single` | 37 / 34 / 30 | **39 / 34 / 30** (`+2 / 0 / 0`) | `134.1 ms → 94.9 ms` (**-29.2%**) |
| **`scan`** (40 pos) | `indexed_class` | 34 / 30 / 26 | **37 / 30 / 27** (`+3 / 0 / +1`) | `340.4 ms → 85.1 ms` (**4.00×**) |
| **`equation`** (35 pos) | `indexed_single` | 29 / 23 / 23 | **32 / 25 / 25** (`+3 / +2 / +2`) | `120.1 ms → 90.6 ms` (**-24.6%**) |
| **`concept`** (34 pos) | `indexed_single` | 33 / 29 / 26 | **32 / 31 / 31** (`-1 / +2 / +5`) | `117.3 ms → 96.9 ms` (**-17.4%**) |
| **`caption`** (2 pos) | `indexed_single` | 2 / 2 / 1 | **2 / 2 / 2** (`0 / 0 / +1`) | `102.95 ms → 87.75 ms` (**-14.8%**) |

**Điểm đáng chú ý**:
- Trên tài liệu **`native`**, `quotable_support` tăng mạnh từ **`33/50 → 40/50`** (`+14%` tuyệt đối) nhờ chiếu đúng display formula/table trong `canonical_text.py`, giữ công thức nguyên khối trong `idp-text-chunking-10`, và không cắt vỡ câu có dấu `;` trong ngoặc đơn.
- Thời gian build corpus tăng nhẹ do số chunk tăng từ `293 → 329` (`native`: `186.6s → 207.8s`) và `258 → 271` (`scan`: `158.3s → 166.8s`) — đây là chi phí 1 lần lúc ingest, bù lại mọi truy vấn về sau nhanh hơn rõ rệt.

---

## 3. Phân tích Micro-profiler các điểm nghẽn hiệu năng

Đo chi tiết trên **20 truy vấn** thực tế (BGE-M3 ONNX CPU, 2 tài liệu `native` + `scan`) trước và sau đợt tối ưu hiệu năng (`efd833c`):

| Giai đoạn / Hàm | Trước tối ưu (Update 2b) | Sau tối ưu (Update 2c) | Mức tăng tốc | Kỹ thuật áp dụng & Nơi cài đặt |
| --- | :---: | :---: | :---: | --- |
| `fit_quotable_evidence(question=q)` | `1,062.8 ms` (max `1,424.1 ms`) | **`25.6 ms`** (max `55.7 ms`) | **41.5×** | Validate span 1 lần/item (`services/rag/citations/source_quotes.py`) + cập nhật O(N) cộng dồn (`services/ai`) |
| `counter.count()` trong `_retrieve_records` | `452.0 ms` | **`74.6 ms`** | **6.1×** | Lưu `_search_text_tokens` lúc load retriever + cận cộng token an toàn trong `services/rag/packing/neighbor_context.py` |
| `_retrieve_records` (2 doc, cached vec) | `588.8 ms` | **`83.2 ms`** | **7.1×** | Tối ưu `neighbor_context` + chạy song song đa tài liệu qua `ThreadPoolExecutor` (`services/ai`) |
| Full `_retrieve` (lần đầu: encode + search + fit) | `580.5 ms` | **`173.7 ms`** | **3.3×** | Cộng hưởng 3 tối ưu trên (thời gian còn lại chủ yếu là ~75 ms encode câu hỏi ONNX CPU) |
| Full `_retrieve` (lặp lại: LRU cache hit) | `580.5 ms` | **`108.3 ms`** | **5.4×** | Cache LRU 256 vector truy vấn an toàn đa luồng (`services/ai`) |
| Kết nối HTTP gọi LLM API | Tạo TCP/TLS mới mỗi request | **Tái sử dụng keep-alive pool** | Loại bỏ bắt tay TLS lặp | `httpx.Client` (`max_connections=32`, `max_keepalive_connections=16`) trong `services/rag/generation/openai_compatible.py` |

**Kiểm chứng tương đương (Zero Behavior Drift)**:
- Đối chiếu đầu ra `fit_quotable_evidence` bản tối ưu với bản O(N²) cũ trên **100/100** trường hợp: **`0` sai lệch**.
- Đối chiếu `neighbor_context` với cận cộng token an toàn vs chạy BPE trực tiếp: giữ nguyên tuyệt đối thứ tự `items` và giá trị `budget_count` (có unit test trong `tests/test_retrieval_search_fixes.py`).

---

## 4. Tác động chuẩn hóa chính tả tiếng Việt (Layer A & opt-in Layer B)

Báo cáo đo trực tiếp trên cùng corpus BGE-M3 `idp-text-chunking-10`:

| Bộ kiểm thử | Cấu hình | `Recall@5` | `gold_page_packed` | `MRR` | `matched_terms` |
| --- | --- | :---: | :---: | :---: | :---: |
| **19 câu `rag-100` đảo chính tả** (kiểu dấu cũ/mới, `i`/`y`) — BM25 only | Layer A OFF | 17 / 19 | 17 / 19 | `0.8012` | 287 |
| | **Layer A ON (mặc định)** | **18 / 19** | **19 / 19** | **`0.8114`** | **295** |
| **19 câu `rag-100` đảo chính tả** — Full Hybrid | Layer A OFF | 18 / 19 | 19 / 19 | `0.8158` | 287 |
| | **Layer A ON (mặc định)** | **19 / 19** | **19 / 19** | **`0.8175`** | **295** |
| **15 câu chính tả hiện đại trên SGK** — BM25 only | Layer A OFF | 12 / 15 | 12 / 15 | `0.6989` | 141 |
| | **Layer A ON (mặc định)** | **12 / 15** | **12 / 15** | **`0.7061`** | **160 (+19/19)** |
| **90 câu `rag-100` single-doc** — Hybrid + Layer B opt-in | `lexical_folded_boost=0.0` (mặc định) | 84 / 90 | 85 / 90 | — | `packed_support`: 74 |
| | `lexical_folded_boost=0.25` (opt-in) | 84 / 90 | **86 / 90** | — | `packed_support`: **76** |

> **Lý do giữ Layer B mặc định `0.0`**: Trên từ vựng SGK Toán 10, phép bỏ dấu toàn phần gây `377 / 1,916` nhóm va chạm đồng âm (ví dụ `hàm` / `ham`, `đồ` / `độ`). Vì vậy Layer A luôn bật (an toàn, không va chạm), còn Layer B để opt-in qua `RetrievalConfig(lexical_folded_boost=...)`.

---

## 5. Kiểm chứng End-to-End với LLM thật

### 5.1. Bộ Holdout 19 câu (`14` positive / `5` negative, `deepseek/deepseek-v4.1-flash`)

| Phiên bản | Trả lời đúng & trích đúng trang gold | Negative bị bịa | Lỗi hệ thống | Độ trễ median |
| --- | :---: | :---: | :---: | :---: |
| Trước fix quote/context (`skip_paren_semicolon`, multiline snap, context 16k) | `10 / 14` (`71.4%` — 4/7 native, 6/7 scan) | `0 / 5` | `0` | `3,199.2 ms` |
| **Sau fix quote/context** | **`13 / 14` (`92.9%`)** | **`0 / 5`** | **`0`** | **`2,429.1 ms`**\* |

*\*Lượt 1 đạt `13/14` (7/7 native, 6/7 scan, median `2,429.1 ms`); lượt 2 có ghi đầy đủ `claims` đạt `13/14` (6/7 native, 7/7 scan, median `3,687.8 ms` do biến động latency từ nhà cung cấp API).*

### 5.2. Bộ quy mô lớn `rag-100` (90 positive / 10 negative, `deepseek/deepseek-v4.1-flash-1017` qua `deepinfra/fp8`)

Chạy trước đợt tối ưu hiệu năng `efd833c` (khi `ret_ms` median vẫn là `1,450.4 ms` và `llm_ms` median là `3,100.2 ms`):

- **`gold_in_evidence`**: **`82 / 90` (`91.1%`)**
- **`answered_citing_gold`**: **`64 / 90` (`71.1%`)**
  - `concept`: **`30 / 34` (`88.2%`)**
  - `data`: **`3 / 3` (`100%`)**
  - `equation`: `21 / 35` (`60.0%` — nhiều câu yêu cầu đọc biểu thức LaTeX dày đặc)
  - `table`: `4 / 7` (`57.1%`)
  - `exercise`: `3 / 7` (`42.9%`)
- **`negatives_answered`**: `2 / 10` (`q091`, `q098` — model giá rẻ tự suy diễn nhẹ dù bằng chứng không khớp hoàn toàn; cần theo dõi prompt refusal nếu dùng model nhẹ).
- **`errors`**: **`0 / 100`**.
- **Độ trễ**: median `4,398.6 ms` (sau khi áp dụng tối ưu retrieval `efd833c` kéo phần retrieval xuống `~95–174 ms`, phần chi phối chính còn lại là độ trễ mạng/suy luận của LLM).

---

## 6. Kiểm thử tự động & Giới hạn còn mở

- **Kiểm thử tự động**: Toàn bộ bộ test `services/rag` chạy trực tiếp trên nhánh `feature/lumi-web-deepdoc-rag` đạt **`295 passed, 0 failed`** trong `28.38s` (Windows, Python 3.12, offline, không phụ thuộc GPU hay API ngoài).
- **Giới hạn đã biết**:
  1. Các bundle tạo bằng `idp-text-chunking-7` hoặc `idp-text-chunking-8` **không tương thích ngược** và cần chạy `build_corpus` lại sang `idp-text-chunking-10`.
  2. Nhánh `feature/lumi-web-deepdoc-rag` chỉ chứa `services/rag` và `services/core`; các tối ưu mức ứng dụng (`fit_quotable_evidence` O(N), vector LRU cache, parallel multi-doc retrieval) nằm ở `services/ai` và cần đồng bộ khi merge `services/ai`.
  3. Độ trễ gọi LLM thật phụ thuộc nhà cung cấp API; keep-alive pooling giảm overhead kết nối TLS nhưng không thay đổi thời gian sinh token của mô hình.
