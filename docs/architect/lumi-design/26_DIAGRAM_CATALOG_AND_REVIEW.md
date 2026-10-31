# PHỤ LỤC — DANH MỤC SƠ ĐỒ VÀ QUY TRÌNH KIỂM SOÁT THAY ĐỔI

**Mã:** LUMI-DIAGRAMS-002 · **Trạng thái:** DRAFT. Các sơ đồ trong repository được lưu ở dạng Mermaid `.mmd` và hiển thị trực tiếp trong các chương; bản PNG/SVG chỉ là xuất bản phục vụ in ấn. Không chứa ảnh screenshot từ tài liệu doanh nghiệp khác.

## 1. Danh mục 16 sơ đồ

| Mã hình | Tên tệp (bỏ extension) | Ý nghĩa / tính chính xác |
|---|---|---|
| A01 | A01_System_Context_Current | Hiện trạng User → Web → Core → DB/SMTP |
| A02 | A02_Capability_Map | Core hiện tại và các service dự kiến phân biệt trạng thái |
| A03 | A03_Layered_Architecture | Mô hình tầng logic; không phải topology vật lý |
| A04 | A04_Container_Runtime | Các runtime của Docker Compose hiện có |
| A05 | A05_Core_Component | Các module Common/Identity/Classroom/Social/Notification/Admin |
| A06 | A06_Deployment_Local | Docker Compose local trên một host |
| A07 | A07_Deployment_CI | CI jobs trong quy trình xử lý hiện tại |
| A08 | A08_Deployment_Cloud_Mock | Production mock theo repo; chưa live re-verification |
| A09 | A09_Trust_Boundaries | Biên an toàn và luồng kiểm tra permission |
| A10 | A10_Seq_Student_Activation | Quy trình xử lý Student onboarding |
| A11 | A11_Seq_Class_Notification | Transaction outbox/recipient inbox |
| A12 | A12_Core_Data_Domains | ERD mức miền, không thay full physical DB ERD |
| A13 | A13_Release_Pipeline | Pipeline hiện có + gate phát hành đề xuất |
| A14 | A14_Experimental_Environments | Chuỗi môi trường/môi trường thực nghiệm và evidence |
| A15 | A15_Logical_Service_Boundaries | Ranh giới Document/Learning/LI tương lai, không có AI design |
| A16 | A16_Incident_Recovery | Khung incident/recovery được đề xuất |

## 2. Ý nghĩa của các trạng thái thể hiện trên sơ đồ

`CODE-GROUNDED` mô tả kiến trúc xuất hiện trong file ở commit tham chiếu; không tự chứng minh đã chạy hoàn hảo. `REPORTED DEPLOYMENT` có bằng chứng ghi trong tài liệu dự án nhưng chưa truy xuất runtime trong đợt biên soạn. `PROPOSED` là hướng đề xuất để review/triển khai. `NOT DESIGNED` không có API/schema/service internals.

## 3. Cập nhật và quản lý phiên bản sơ đồ

1. Chọn đúng sơ đồ bị ảnh hưởng; cập nhật `.mmd` và các đoạn Mermaid nhúng cùng một lần thay đổi.
2. Đối chiếu `Business Rules`, `00_INDEX.md`, `API_CONTRACT.md`, `compose.yaml`, CI và migration khi sơ đồ thay đổi.
3. Nếu thay đổi trách nhiệm module/service hoặc mạng, cập nhật Architecture Atlas, deployment và ADR cùng lúc.
4. Không sửa hình PNG thủ công dẫn tới lệch mã nguồn. Chỉ dùng PNG/SVG là rendered outputs.
5. Mỗi release ghi Git commit + reviewer + ngày kiểm tra; không dùng sơ đồ draft làm evidence triển khai.

## 4. Tiêu chí thẩm định sơ đồ

- [ ] Hình đọc được trên nền trắng, không có icon/trang trí thừa; nhãn tiếng Việt và thuật ngữ gốc đủ rõ.
- [ ] Các khối thể hiện đúng boundary; có hướng mũi tên và protocol/logic được giải thích trong chapter.
- [ ] Service chưa có code dùng nét đứt, không vẽ như live dependency.
- [ ] Sơ đồ topology khác với sơ đồ tầng logic; không copy kết quả triển khai đề xuất thành hiện trạng.
- [ ] Mỗi hình có mã Axx, đường dẫn nguồn `.mmd`, không nhầm tên file.
- [ ] Các giá trị RTO/RPO, size VM, region, auth secrets chưa được đo hoặc chốt không được ghi số cụ thể.