# Kiến trúc hệ thống
Internet -> Nginx HTTPS -> Next.js và public API của Core, Document, Learning, AI, Notification. Private service network cho internal REST. PostgreSQL chung instance, database/credential riêng Core/Document/Learning/Notification; AI tự chọn storage. Document persistent volume; AI derived index riêng. Worker là tiến trình hỗ trợ, không phải microservice nghiệp vụ thứ sáu. Không SQL/JOIN/FK xuyên service. Single VPS và PostgreSQL là SPOF; không tuyên bố HA. RAG library trong AI, thuật toán do nhóm AI/RAG sở hữu.
| Service | Ownership |
|---|---|
| Core | Identity, auth, classroom, membership, feed/comment |
| Document | File/version/grant, ingestion orchestration |
| Learning | Questions, assessment, attempts, grades, analytics |
| AI | Index, retrieval, generation, conversation, AI jobs |
| Notification | Inbox, recipient, notification/read state |
Kế thừa các design record đã accepted; không tự thay đổi contract.