# Public API — LRN-T03
Prefix /api/v1 mục tiêu, đối chiếu frontend hiện có.
| Method | Path |
|---|---|
| GET POST | /classrooms/{id}/questions |
| GET PATCH DELETE | /questions/{id} |
| GET POST | /questions/{id}/versions |
| GET POST | /classrooms/{id}/assessments |
| GET PATCH DELETE | /assessments/{id} |
| POST | /assessments/{id}/publish, /assessments/{id}/archive |
| GET POST | /classrooms/{id}/assignments |
| GET PATCH | /assignments/{id} |
| POST | /assignments/{id}/publish, /assignments/{id}/close |
| GET POST | /assignments/{id}/attempts |
| POST | /classrooms/{id}/practice-sessions |
| GET | /practice-sessions/{id}, /attempts/{id} |
| PUT | /attempts/{id}/answers/{item_id} |
| POST | /attempts/{id}/submit, /attempts/{id}/grade |
| GET | /attempts/{id}/result |
| PATCH | /grades/{id} |
| GET | /grades/{id}/history |
| POST | /attempts/{id}/publish-result |
| GET | /classrooms/{id}/analytics, /classrooms/{id}/analytics/me, /classrooms/{id}/analytics/students/{uid}, /classrooms/{id}/recommendations/me |
| POST | /classrooms/{id}/question-generation-jobs, /attempts/{id}/ai-grading-jobs |
| GET | /ai-jobs/{id} |
Kế thừa error envelope, pagination, status/request ID DOC-T03. Actor từ verified JWT, Core membership + local resource authorization. Student DTO không answer_key/rubric bí mật/điểm chưa công bố. Autosave revision conflict 409; async job 202; DTO/OpenAPI chi tiết sau discovery. Practice session mapping và reopening endpoint cần chốt.