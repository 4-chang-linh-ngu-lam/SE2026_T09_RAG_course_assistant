# Notification — ACCEPTED 25/11/2026
Người dùng phê duyệt NTF-D01–05 và NTF-T01–05.
- D01: sở hữu notification, recipient, read state, event history.
- D02: in-app; email nghiệp vụ/push hoãn, SMS ngoài scope.
- D03: async REST + transactional outbox nguồn, durable inbox 202, không broker.
- D04: recipient theo quyền hiện hành, Core membership và Learning assignment/completion.
- D05: frontend polling 30s đề xuất, jitter, pause background, refresh khi focus/open.
- T01: PostgreSQL riêng, 4 bảng logic.
- T02: 7 public endpoints.
- T03: POST /internal/v1/events, durable inbox/job, dedup.
- T04: service JWT, retry, lease, fault isolation, deletion workflow.
- T05: 20 AC, 8 tasks.
Thiết kế mục tiêu chưa đối chiếu đầy đủ code, chưa test. Chi tiết 01–08.