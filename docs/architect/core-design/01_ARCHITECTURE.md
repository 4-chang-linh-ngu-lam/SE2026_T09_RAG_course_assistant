# Kiến trúc Core

CORE-D01–08 ACCEPTED và được hiệu chỉnh bởi CORE-CR01–04. Core sở hữu Identity, School, Course/SubjectClass, student membership, teaching assignments, Social, Notification hiện hành, Administration và audit. Mỗi service khác sở hữu database/credential riêng; không SQL/FK xuyên service. Core cung cấp current user/class authorization; service sở hữu resource vẫn kiểm tra quyền local.

System roles là ADMIN/LECTURER/STUDENT. Student roster dùng AUTO/MANUAL; Lecturer assignment dùng PRIMARY/ASSISTING. Chỉ Admin tạo lớp chính khóa, chỉnh roster/teaching assignment, archive/restore. Lecturer chỉ dạy trong lớp được phân công. Không có class OWNER role, join code, invitation self-join, Student self-leave hoặc teacher owner-transfer trong Lumi MVP.

Document sở hữu file/version/grant; Learning sở hữu question/attempt/grade; AI sở hữu index/retrieval/generation/conversation; Notification là service độc lập trong target architecture nhưng hiện còn là module/worker trong Core. Core outbox là producer boundary; service khác không truy cập Core DB.

CORE-CR01–04 supersede các phần mâu thuẫn trong CORE-D03/D04 và CORE-T01–03/T05/T06/T08. BUSINESS_RULES.md và Core API Contract là nguồn nghiệp vụ.
