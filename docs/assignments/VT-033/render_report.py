"""Render the submission from verified evidence, using isolated PDF tooling.

Windows: py -3.12 docs/assignments/VT-033/render_report.py
Requires reportlab on the reporting-only path and installed PyMuPDF/pypdf for QA.
No report dependency is added to the application.
"""

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOCS = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "services/core/.venv/reporting-deps"))

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)


def main():
    summary = json.loads((DOCS / "submission.json").read_text(encoding="utf-8-sig"))
    load = json.loads((DOCS / "evidence/07-load.json").read_text(encoding="utf-8-sig"))
    legacy = json.loads((DOCS / "evidence/07-load-httpx.json").read_text(encoding="utf-8-sig"))
    default_pool = json.loads((DOCS / "evidence/07-load-httpx2-default-pool.json").read_text(encoding="utf-8-sig"))
    mutation = json.loads((DOCS / "evidence/03-mutation.json").read_text(encoding="utf-8-sig"))
    for name, file in (("Arial", "arial.ttf"), ("Arial-Bold", "arialbd.ttf")):
        pdfmetrics.registerFont(TTFont(name, "C:/Windows/Fonts/" + file))
    pdfmetrics.registerFontFamily("Arial", normal="Arial", bold="Arial-Bold")
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("BodyVI", fontName="Arial", fontSize=10, leading=14, spaceAfter=8))
    styles.add(ParagraphStyle("SmallVI", parent=styles["BodyVI"], fontSize=8.1, leading=11))
    styles.add(ParagraphStyle("TitleVI", parent=styles["BodyVI"], fontName="Arial-Bold",
                              fontSize=25, leading=31, textColor=colors.HexColor("#163449")))
    styles.add(ParagraphStyle("HeadingVI", parent=styles["BodyVI"], fontName="Arial-Bold",
                              fontSize=16, leading=21, spaceAfter=13,
                              textColor=colors.HexColor("#163449")))
    styles.add(ParagraphStyle("SubVI", parent=styles["BodyVI"], fontName="Arial-Bold",
                              fontSize=11, leading=15, textColor=colors.HexColor("#147D83")))
    styles.add(ParagraphStyle("MetricVI", parent=styles["BodyVI"], fontName="Arial-Bold",
                              fontSize=16, leading=22, alignment=TA_CENTER))
    story = []

    def p(text, style="BodyVI"):
        story.append(Paragraph(text, styles[style]))

    def heading(text):
        p(text, "HeadingVI")
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#147D83")))
        story.append(Spacer(1, 12))

    def table(headers, rows, widths, small=True):
        style = styles["SmallVI" if small else "BodyVI"]
        cells = [[Paragraph(html.escape(str(c)), style) for c in headers]]
        cells += [[Paragraph(html.escape(str(c)), style) for c in row] for row in rows]
        result = Table(cells, colWidths=widths, repeatRows=1, hAlign="LEFT")
        result.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E3F0F2")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.7, colors.HexColor("#147D83")),
            ("LINEBELOW", (0, 1), (-1, -1), 0.3, colors.HexColor("#CFD9DF")),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(result)
        story.append(Spacer(1, 10))

    def new_page():
        story.append(PageBreak())

    def link(url, label):
        return f'<link href="{html.escape(url, quote=True)}" color="#147D83"><u>{label}</u></link>'

    cov = summary["coverage"]
    repo = summary["repository"]
    p("BÀI TẬP CÁ NHÂN 3", "SubVI")
    p("VT-033<br/>Kiểm thử cấu hình<br/>Notification", "TitleVI")
    story.append(Spacer(1, 16))
    p("<b>Mai Huy Hoàng · MSSV 23001878</b><br/>SE2026-T09 · Thành viên<br/>AI-01 - RAG trợ giảng cho tài liệu môn học")
    p(link(repo, "GitHub repository") + " · " + link(summary["branch_url"], "Branch cá nhân")
      + " · " + link(summary["pr_url"], "Draft PR #" + str(summary["pr_number"])))
    p("Baseline: " + summary["baseline_sha"], "SmallVI")
    p("Implementation: " + summary["implementation_sha"], "SmallVI")
    p("Snapshot kiểm chứng: " + summary["verification_sha"], "SmallVI")
    table(["Kiểm chứng local", "Kết quả quan sát"], [
        ["RED / GREEN Notification", "2 RED đúng assertion; 69 passed, 0 failed, 0 skipped"],
        ["Full Core", summary["full_result"]],
        ["Authorization mutation", "KILLED; exact-byte restore và 3 test bảo mật pass lại"],
        ["120 tác vụ / p95 client", f'{load["requests"]} requests; {load["client_p95_ms"]:.1f} ms / 3500 ms; gate={"PASS" if load["passed_vt033"] else "FAIL"}'],
        ["Trạng thái GitHub", summary["ci_result"] + "; PR Draft/OPEN, chưa merge"],
    ], [154, 357])
    if not load["passed_vt033"]:
        p('<font color="#B42318"><b>Gate tải 120: FAIL.</b> p95 thấp hơn 3500 ms ở profile cuối '
          'vẫn chưa đủ vì còn lỗi HTTP/transport. Không tuyên bố nghiệm thu NFR.</font>')
    p("Cam kết theo mẫu đề bài (sinh viên cần đọc/xác nhận trước khi nộp):", "SubVI")
    p('“Tôi chịu trách nhiệm về toàn bộ code, test và nội dung bài làm; tôi đã khai báo việc sử dụng AI.”')
    p("Báo cáo được AI hỗ trợ soạn từ evidence local. Không giả định sinh viên hoặc owner đã duyệt. "
      "8 trang nội dung chính; phụ lục A-B chứa AI Usage Log và trích evidence.", "SmallVI")

    new_page()
    heading("1. Specification và invariant")
    p("<b>Problem statement.</b> Default 20 nằm trong pagination dùng chung. Cho phép vận hành thay đổi "
      "default của riêng Notification tại một Settings field, tránh sửa nhiều call site và tránh làm "
      "thay đổi Classroom, Identity, Social hoặc Administration.")
    for ac, text in [
        ("AC1", "Env vắng mặt:20. NOTIFICATION_PAGE_SIZE_DEFAULT nhận số nguyên1..100; Settings validate khi process khởi tạo. Env sai chặn startup; đổi env cần restart."),
        ("AC2", "Query limit hợp lệ1..100 ghi đè default. 0,101,noninteger bị từ chối; cursor lỗi/ngoài inbox vẫn bị từ chối; list không ghi dữ liệu."),
        ("AC3", "Giữ items/unread_count/next_cursor, sequence DESC, đúng ID/payload/read/created_at, cursor tiếp nối và unread count toàn inbox; no-store."),
        ("AC4", "Identity hiện hành và quyền recipient giữ nguyên. A không đọc/mark-read dữ liệu B; B.read_at không đổi. Khóa tài khoản từ chối; read-all/idempotency giữ nguyên."),
        ("AC5", "Endpoint khác vẫn mặc định20. Không đổi schema/migration, permission, framework hoặc dependency; chạy regression Core trên PostgreSQL test riêng."),
    ]:
        p(f"<b>{ac}.</b> {text}")
    p("Invariant và điều kiện", "SubVI")
    p("A không bao giờ đọc hoặc đánh dấu đã đọc notification của B, bất kể cấu hình pagination. "
      "Pre: Settings hợp lệ, user ACTIVE hiện hành, DB/Identity khả dụng, cursor thuộc inbox. "
      "Post: list là lát cắt own-inbox đúng thứ tự, không đổi read state; cross-recipient PATCH trả404 "
      "và giữ nguyên B.read_at; lỗi transaction rollback.")
    p("Ràng buộc phi chức năng", "SubVI")
    p("Patch production chỉ 2 file, dùng pydantic-settings và cursor helper sẵn có. Tải 120 tác vụ qua "
      "HTTP thật/PostgreSQL16, client p95≤3500ms và không lỗi ownership. Chỉ dữ liệu tổng hợp, "
      "không log JWT/DSN; không chạm database vận hành hoặc xóa volume.")

    new_page()
    heading("2. Kế hoạch AI và chiến lược theo rủi ro")
    p("Plan được lưu trước code; agent chỉ đọc khác review theo yêu cầu người dùng. RED commit "
      + summary["red_sha"][:12] + " có trước implementation " + summary["implementation_sha"][:12] + ".")
    table(["Đề xuất AI thật", "Quyết định sau review repository"], [
        ["P1 sửa get_pagination chung", "Sửa kế hoạch: dependency riêng Notification. pagination.py:39 và nhiều consumer dùng chung."],
        ["P2 nạp env mỗi request", "Bác bỏ: Settings singleton config.py:76 ở baseline; dùng field đã load, cần restart."],
        ["P3 chỉ mock service", "Chỉ dùng cho RED route; bổ sung PostgreSQL để chứng minh ID/cursor/read_at."],
        ["P4 tăng cap class harness", "Bác bỏ: chỉ tạo100 actor, đo classes/backend500ms; tạo harness Notification riêng."],
    ], [158, 353])
    p("R1 status-only che business error; R2 regression shared default; R3 config không hợp lệ; "
      "R4 sai read state/rollback; R5 hiểu sai bằng chứng tải. Unit/API và PostgreSQL bổ sung cho nhau. "
      "Không tạo browser E2E mới cho biến môi trường backend; Core HTTP journey hiện có vẫn được chạy.", "SmallVI")
    p("Test cases 1-9 (C = test_vt033_config.py; P = test_vt033_postgres.py)", "SubVI")
    cases = summary["test_cases"]
    table(["ID", "Risk/AC", "Level", "Input/pre", "Business outcome", "P", "File/function"],
          [row for row in cases[:9]], [30, 46, 48, 72, 151, 24, 140])

    new_page()
    heading("3. Test cases và test-first")
    table(["ID", "Risk/AC", "Level", "Input/pre", "Business outcome", "P", "File/function"],
          [row for row in cases[9:]], [30, 46, 48, 72, 151, 24, 140])
    p("BVA cả config và query: 0,1,2,99,100,101; default20, custom1/2/100 và explicit override. "
      "Negative: T02/T04/T07/T11/T12/T14/T17; failure path T15 gây lỗi SQL thật rồi kiểm tra phục hồi.", "SmallVI")
    p("RED → GREEN", "SubVI")
    p("Route RED: expected Pagination(limit=2), actual20. PostgreSQL RED: expected2 own IDs, "
      "actual20 (thừa18); cả hai exit1 và application hash khớp baseline. Sau patch, toàn Notification "
      "69 passed, exit0. Không dùng lỗi import/DB để thay RED. Evidence: 01-red-*.log, 02-green-notification.log.", "SmallVI")
    p("Dòng production quan trọng: Field(default=20,ge=1,le=100) validate config; Query giữ bounds/cursor "
      "length; limit is None phân biệt omission; gọi helper bằng explicit args; route đổi sang dependency "
      "local. Service/repository/auth và shared helper giữ nguyên. API contract/README được cập nhật.", "SmallVI")

    new_page()
    heading("4. Who tests the tests?")
    p("Authorization mutation", "SubVI")
    p("Sau commit implementation đúng, tạo detached worktree trong venv, không push. Chỉ bỏ predicate "
      "Notification.recipient_id == user_id khỏi mark_read. Cùng test thực thi qua Identity/API/repository "
      "và PostgreSQL; assert persisted B.read_at trước khi assert HTTP status.")
    table(["Giai đoạn", "Quan sát / evidence"], [
        ["Đúng trước mutation", "3 passed (default1/2/100), exit0 / 03-before.log"],
        ["Bỏ một guard", "3 failed, exit1; persisted read_at bị thay đổi / 03-killed.log"],
        ["Khôi phục", "3 passed, exit0; exact-byte SHA256 bằng nhau; main source không đổi / 04-restored.log"],
        ["Guard / commit", "03-mutation.diff chỉ có thay đổi một predicate; không có mutant source trong branch nộp"],
    ], [145, 366])
    p("Source SHA256 trước/sau: " + mutation["original_source_sha256"], "SmallVI")
    p("Coverage", "SubVI")
    p(f'Full app: line {cov["line_percent"]:.2f}% ({cov["covered_lines"]}/{cov["num_statements"]}); '
      f'branch {cov["branch_percent"]:.2f}% ({cov["covered_branches"]}/{cov["num_branches"]}). '
      f'Notification router/service/repository: {summary["notification_coverage"]}. '
      "Không kết luận chất lượng chỉ từ phần trăm; xem missing lines/branches trong coverage-summary.md.")
    p("Flaky experiments", "SubVI")
    p(summary["flaky_summary"])
    p("Giảm rủi ro bằng fresh sibling DB, monkeypatch/override được dọn sau test, sequence ID rõ ràng "
      "và Event/barrier thay kỳ vọng theo đồng hồ. Số lần lặp hữu hạn chưa chứng minh không bao giờ flaky.")

    new_page()
    heading("5. Tải thực tế 120 tác vụ")
    table(["Phép đo", "Kết quả"], [
        ["Actors / actual tasks / peak in-flight", f'{load["load"]["configured_actors"]} / {load["actual_tasks"]} / {load["peak_client_in_flight"]}'],
        ["Warmup / đo / elapsed", f'{load["load"]["warmup_seconds"]}s / {load["load"]["configured_seconds"]}s / {load["elapsed_seconds"]:.2f}s'],
        ["Requests / HTTP statuses", f'{load["requests"]} / {load["status_counts"]}'],
        ["Errors / ownership / timeout", f'{load["errors"]} / {load["content_or_ownership_errors"]} / {load["timeouts"]}'],
        ["Client p50 / p95 / p99 / max", " / ".join(f'{load[k]:.1f}ms' for k in ("client_p50_ms","client_p95_ms","client_p99_ms","client_max_ms"))],
        ["Backend p50 / p95 / p99 / max", " / ".join(f'{load[k]:.1f}ms' for k in ("backend_p50_ms","backend_p95_ms","backend_p99_ms","backend_max_ms"))],
        ["Target / verdict", f'p95 client≤3500ms; passed_vt033={load["passed_vt033"]}'],
        ["Run ID / patch SHA", load["run_id"] + " / " + load["patch_sha"][:12]],
    ], [181, 330])
    env = load["environment"]
    p("Mô hình", "SubVI")
    p(f'120 inbox/user/JWT tổng hợp riêng, {load["load"]["rows_per_actor"]} notifications/user; '
      "một barrier đồng bộ; closed-loop, zero think time; "
      "không phải arrival rate cố định. Warmup hoàn tất trước đo. Request gọi app Uvicorn thật qua "
      "loopback, Identity DB thật, không override auth/service. So sánh chính xác ID, payload, read flag, "
      "cursor, unread count và no-store theo từng actor.")
    p(f'Máy: {html.escape(env["os"])}; {html.escape(env["cpu"])}; {env["logical_cpus"]} logical CPUs; '
      f'RAM {env["ram_bytes"]/1024**3:.1f}GiB. Python {env["python"]}; PostgreSQL {env["postgresql"]}; '
      f'pool {env["pool_size"]}+{env["max_overflow"]}; admission {env["admission_capacity"]}.', "SmallVI")
    p(f'Đối chứng HTTPX 0.28.1/pool 5+10: '
      f'{legacy["requests"]} requests, p95 client {legacy["client_p95_ms"]:.1f}ms, '
      f'backend {legacy["backend_p95_ms"]:.1f}ms, FAIL. Giữ nguyên app/DB/pool/target; '
      "lượt HTTPX2/pool 5+10 chỉ đổi thư viện client đã có trong dev dependency. Các lượt được lưu riêng, không thay FAIL thành PASS.", "SmallVI")
    p(f'HTTPX2/pool5+10: {default_pool["requests"]} requests, p95 {default_pool["client_p95_ms"]:.1f}ms, '
      f'{default_pool["errors"]} errors, FAIL. Profile15+0 giữ cùng maximum15 kết nối/admission14; '
      "đã có hướng dẫn trong Core tests README. Production defaults không đổi. Ba lượt được báo cáo riêng.", "SmallVI")
    p("Client và server chia sẻ máy/process, Docker/WSL và workload nền không cách ly. "
      "120 request client in-flight không phải120 SQL đồng thời. Đây là workload list hữu hạn; "
      "chưa chứng minh mixed writes, browser/network thật, thời gian dài hoặc năng lực production.")

    new_page()
    heading("6. Traceability, AI trust và review")
    table(["AC / risk", "Test ID và file/function", "Commit / evidence / observed"], [
        ["AC1 / R3", "T01-T05,T09,T16 / C::test_settings_*, test_route_resolves_default; P::test_configured_inbox_business_outcome", summary["red_sha"][:12]+" RED → "+summary["implementation_sha"][:12]+" GREEN; 01-red*,02-green*"],
        ["AC2 / R1", "T06-T07,T10-T11,T17 / C query tests; P explicit-limit and foreign-cursor", "GREEN full JUnit / exact IDs and unchanged state"],
        ["AC3 / R1,R4", "T09-T10,T15-T16 / P business pages, SQL-failure recovery", "GREEN + coverage; precise cursor/count/read/payload"],
        ["AC4 / R1,R4", "T11-T14 / P cross-recipient, locked-account, own/read-all", "03-before PASS → mutant KILLED →04-restored PASS"],
        ["AC5 / R2", "T08 / C::test_other_endpoint_keeps_twenty; entire Core regression", summary["full_result"]+"; unchanged shared helper/source diff"],
        ["NFR / R5", "T18 / performance/vt033_notification_load.py", "FAIL:248 HTTP/transport errors; 07-load.json; p95 alone is insufficient"],
    ], [76, 222, 213])
    p("Hai điểm AI có vẻ hợp lý nhưng chưa đáng tin", "SubVI")
    p("1. Mock service trả200 dễ làm test xanh dù repository bỏ recipient guard. Test PostgreSQL "
      "kiểm tra read_at thật và mutation đã chứng minh oracle phát hiện lỗi quyền.")
    p("2. Tăng --users lên120 trên class harness vẫn chỉ có100 actor và đo endpoint/threshold khác. "
      "Harness mới ghi actual_tasks/peak_in_flight và gate theo client p95≤3500ms.")
    p("Human review pending", "SubVI")
    p("Notification owner (TV4), Common/Identity consumers cần review shared Settings và contract. "
      "Sinh viên cần đọc/chỉnh reflection, log và cam kết. Draft PR ghi DO NOT MERGE; không tự gán "
      "human-approved. " + link(summary["ci_url"], "CI run thật") + ".")

    new_page()
    heading("7. Reflection và giới hạn")
    reflection = (DOCS / "reflection.md").read_text(encoding="utf-8").strip()
    words = len(reflection.split())
    if not 250 <= words <= 350:
        raise ValueError(f"Reflection must be250..350 words, observed {words}")
    p(f"Reflection tiếng Việt ({words} từ theo whitespace; AI hỗ trợ, sinh viên cần review)", "SubVI")
    for paragraph in reflection.split("\n\n"):
        p(html.escape(paragraph))
    p("Môi trường và giới hạn còn lại", "SubVI")
    p("Baseline Python3.12.0:397 passed,4 failed,1 error (Unicode email và CLI decoding Windows). "
      "Chọn CPython3.12.14 đã cài, giữ nguyên package versions và dùng PYTHONUTF8=1 để verify lại. "
      + summary["full_result"] + ". Không sửa Identity để che baseline failure. "
      "Gate tải 120 vẫn FAIL do 248 lỗi. Load hữu hạn trên máy dùng chung; owner/human review chưa diễn ra.", "SmallVI")
    p("Tái lập", "SubVI")
    p("Xem docs/assignments/VT-033/README.md cho CMD/PowerShell, venv, PostgreSQL test riêng, "
      "RED checkout, GREEN/coverage, mutation và harness. Mọi log đều có timestamp/SHA/command/exit; "
      "credential được khử và whitespace được chuẩn hóa.", "SmallVI")

    new_page()
    heading("Phụ lục A. AI Usage Log")
    p("Công cụ: Codex (dòng GPT-6; không có model build ID chính xác trong runtime). Một agent "
      "Codex chỉ đọc review plan theo lựa chọn rõ ràng của người dùng.")
    p("Prompt chính nguyên văn được lưu ở " + link(repo + "/blob/" + summary["verification_sha"]
      + "/docs/assignments/VT-033/ai-main-prompt.md", "ai-main-prompt.md") + ". Nội dung yêu cầu: "
      "hoàn thiện local VT-033; test-first RED/GREEN, mutation authorization được hoàn nguyên, BVA, "
      "coverage/flaky/120 actors, evidence, Draft PR và PDF; cấm main/merge/force-push/secrets.")
    table(["Tương tác / đề xuất", "Dùng / sửa / bác bỏ", "Kiểm chứng thật"], [
        ["AI tạo plan trước code", "P1/P2/P4 bị sửa/bác bỏ; P3 giới hạn ở routing", "spec-and-plan.md; plan-review.md, baseline citations"],
        ["Người dùng chọn agent review chỉ đọc", "Agent review không sửa file/chạy test", "Review lưu trước production patch"],
        ["AI viết BVA và route RED", "Giữ assert exact Pagination; thêm outcome PG", "01-red-route,01-red-postgres exit1"],
        ["AI viết patch 2 file", "Giữ Settings existing và helper shared", "69 Notification tests; full Core + lint/format"],
        ["AI viết mutation runner", "Chỉ detached worktree, restore finally", "3 pass →3 fail theo read_at →3 pass; source hashes equal"],
        ["AI viết load và báo cáo", "Kiểm tra actor/content/client timing và evidence động", "07-load.json, JUnit, coverage XML; PDF render/text/link QA"],
        ["Client latency investigation", "HTTPX2 đã có trong dev; giữ raw HTTPX FAIL", "3541 requests/p95 17578.75ms FAIL; HTTPX2/default pool cũng FAIL526errors"],
        ["Profile pool15+0 có sẵn", "Giữ maximum15/admission14, không đổi production defaults/target", "7310 requests/p95 3360.44ms nhưng248errors: FAIL, không nghiệm thu NFR"],
    ], [151, 177, 183])
    p("Prompt reviewer đã gửi (trích ý đúng nội dung)", "SubVI")
    p("Review spec-and-plan.md against baseline source, business rules and Core contracts. No edits, "
      "tests or Git mutations. Return independent review with≥2 actual candidates P1-P4 corrected/rejected, "
      "file:line/SHA, minimal implementation, hidden test/load risks and business-rule conflicts. "
      "Do not claim human approval; review required before production patch.", "SmallVI")
    p("AI không thay người học chịu trách nhiệm. Đọc AI trust issues ở trang7, reflection trang8, "
      "và AI usage log đầy đủ trong repository. Không có tuyên bố owner đã duyệt.")

    new_page()
    heading("Phụ lục B. Evidence và GitHub")
    for title, filename, pattern in [
        ("RED route", "01-red-route.log", r"Expected:|Actual:|failed in"),
        ("RED PostgreSQL", "01-red-postgres.log", r"Left contains|failed in"),
        ("Mutation killed", "03-killed.log", r"AssertionError:|failed in"),
        ("Restored", "04-restored.log", r"passed in"),
        ("Full Core", "05-coverage-full.log", r"passed|failed|skipped"),
    ]:
        p(title + " / " + filename, "SubVI")
        text = (DOCS / "evidence" / filename).read_text(encoding="utf-8")
        selected = [line for line in text.splitlines() if re.search(pattern, line)]
        p("<br/>".join(html.escape(line) for line in selected[-4:]) or "See complete linked repository evidence.", "SmallVI")
    p("GitHub delivery", "SubVI")
    p(link(summary["branch_url"], "Branch cá nhân thật") + "<br/>"
      + link(summary["pr_url"], "Draft PR thật - OPEN, base main, chưa merge") + "<br/>"
      + link(summary["ci_url"], "GitHub Actions run: " + summary["ci_result"]))
    p("Branch được kiểm tra không có mutation source; repository.py/service.py/shared pagination "
      "khớp baseline. Evidence diff chỉ mô tả mutation local. GitHub CI xác minh độc lập; "
      "không thay thế RED/GREEN local.")
    p("Các artifact đầy đủ", "SubVI")
    p("00-baseline-*.log/.json,01-red-*,02-green-*,03-mutation.diff/.json,04-restored.log, "
      "05-coverage.xml/.json,06-flaky-*,07-load.json; metadata và commands nằm cùng thư mục. "
      "README chứa exact commands, traceability.md ánh xạ tất cả AC/test/commit/evidence.", "SmallVI")

    output = ROOT / "BT3_23001878_VT-033.pdf"

    def decorate(canvas, doc):
        canvas.setFont("Arial", 8)
        canvas.setFillColor(colors.HexColor("#546B79"))
        label = f"Nội dung chính {doc.page}/8" if doc.page <= 8 else f"Phụ lục {doc.page - 8}"
        canvas.drawString(42, 23, "23001878 · VT-033 · SE2026-T09")
        canvas.drawRightString(A4[0] - 42, 23, label)
        canvas.line(42, 36, A4[0] - 42, 36)

    document = SimpleDocTemplate(str(output), pagesize=A4, leftMargin=42, rightMargin=42,
                                 topMargin=40, bottomMargin=48,
                                 title="BT3 - 23001878 - VT-033", author="Mai Huy Hoàng")
    document.build(story, onFirstPage=decorate, onLaterPages=decorate)
    print(output)


if __name__ == "__main__":
    main()
