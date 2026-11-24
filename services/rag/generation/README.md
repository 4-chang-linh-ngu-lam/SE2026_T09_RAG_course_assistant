# Generation engine (hỏi đáp + sinh câu hỏi)

Trạng thái: **PROPOSED** — hiện thực engine theo bản kiến trúc tầng Generation (2026-11-18).
AI nằm ngoài phạm vi thiết kế của bộ hồ sơ Lumi (OD-20) nên cần ADR riêng trước khi
nối vào `services/ai` (TASK-018) và Learning (TASK-019). Engine **không** gọi Core,
Document hay Learning và không có endpoint; nó nhận evidence đã được lọc theo grant.

## Cấu trúc

```
generation/
  rag_generation.py   Adapter llama.cpp (loopback, khớp SHA, 1 slot). Thêm profile/max_new_tokens/seed
                      theo lần gọi; gọi không tham số vẫn gửi request y hệt bản cũ.
  rag_answer.py, answer_contract.py   Hợp đồng cũ, giữ nguyên (chưa chuyển sang TaskSpec).
  pipeline.py         TaskSpec + GroundedTaskPipeline: pack → grammar → generate → parse →
                      kiểm schema lần 2 → validate → verify → retry seed+1 → provenance
  registry.py         (task, version) → TaskSpec
  runtime/            sampling profiles, SlotScheduler P0/P1/P2, BudgetPlanner, provenance (chỉ hash)
  contracts/          evidence items, citation quote-enum, kiểm JSON-Schema subset, lỗi
  grounding/          số/tên riêng (lexical), bộ tính AST an toàn, judge entailment
  policy/             TutorConfig có kiểu (C6), văn phong theo khối (C4)
  tasks/qa/           quick (C1–C3), condense + route, step (C4), explain ("Vì sao mình sai?"), render (C2/H4)
  tasks/quiz/         knowledge_units, facts, blueprint (QuizSpec), items (4 loại D2), checks,
                      verify (judge + solver), assemble (xáo cân bằng, dedup, đề song song), review (D1), job
  eval/metrics.py     tổng hợp số liệu QAS-06 / chất lượng quiz từ nhãn — không tự tuyên bố KPI
```

## Dùng

```python
from rag.generation.rag_generation import LlamaGenerator
from rag.generation.pipeline import GroundedTaskPipeline
from rag.generation.contracts.evidence import evidence_items
from rag.generation.tasks.qa.quick import answer_quick

generator = LlamaGenerator("http://127.0.0.1:8080", model_path=..., server_path=..., provenance=...,
                           output_ceiling=768)          # >= spec lớn nhất (true_false_4 = 768)
pipeline = GroundedTaskPipeline(generator)              # một pipeline / một scheduler cho cả tiến trình
answer = answer_quick(pipeline, question=q, evidence=evidence_items(records), config=tutor_config,
                      grade=8, wait_timeout=10)         # SchedulerBusy nếu slot bận quá 10 s (QAS-01)
```

Sinh đề: `build_knowledge_units(records, count_tokens=generator.counter.count)` →
`parse_quiz_spec(data)` → `run_job(pipeline, spec, units, job_id=..., fact_cache=..., progress=...)`.
Kết quả chỉ là **bản nháp**; `review.review(...)` rồi `review.export_payload(...)` cho item đã duyệt.

## Bảo đảm do engine cung cấp

- Citation chỉ chọn được từ quote có thật trong evidence (grammar enum) và map về `source_spans`.
- Model không viết tên tài liệu/số trang; `render_answer(answer, locate)` lấy vị trí từ service.
- `insufficient_evidence` là kết quả hợp lệ; không evidence + tắt kiến thức chung ⇒ không gọi model.
- Kiến thức chung (`basis: "general"`) chỉ có trong grammar khi giáo viên bật; UI có nhãn riêng.
- Câu trắc nghiệm: model chỉ sinh đáp án đúng + phương án nhiễu; server xáo có seed, cân bằng vị trí.
- Đúng/sai: ý sai phải bị evidence *phủ định* (judge), không chỉ "không được nhắc tới".
- Trả lời ngắn dạng số: biểu thức tính được kiểm bằng bộ tính AST, không `eval`.
- Provenance mỗi lần gọi: task/version, hash schema/prompt/evidence/raw response, model SHA,
  sampling + seed, token, thời gian, mã lỗi — **không** lưu nguyên văn.

## Service (`services/ai`) phải tự làm — chưa có hợp đồng được duyệt

1. Gate trước mỗi lượt/job: Core access (`ask_new`, `read_history`, `generate_quiz`), lớp ACTIVE (H5),
   Learning không có Assessment chính thức đang mở (D6), Document active grants → lọc evidence. Fail closed.
2. Lưu hội thoại, `StepSession.to_dict()` (không gửi kế hoạch lời giải xuống client), job, ItemDraft.
3. Kiểm grant lúc mở lịch sử: `mask_revoked(rendered, allowed_source_ids)` (H4).
4. Không log nguyên văn câu hỏi/trả lời (E5/F3) — chỉ ghi provenance.
5. Một `GroundedTaskPipeline` dùng chung để scheduler ưu tiên tutor (P0) hơn job nền (P2).

## Việc còn mở

- Quyết định GD-01..GD-07 (mặc định trong `TutorConfig` đánh dấu PENDING).
- Chưa chạy với model thật: chưa có model `.gguf`/llama-server trên máy này. Profile sampling,
  prompt, ngân sách token cần đo bằng bộ vàng trước khi tin (cổng G2/G3).
- Chưa làm: lớp an toàn nội dung cho trẻ vị thành niên, sinh biến thể từ bài tập có sẵn (§5.7),
  retrieval cho tutor (đã gác lại), chuyển `rag_answer` cũ sang TaskSpec.

## Test

`.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/generation` — offline, model giả lập.
