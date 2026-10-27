import { ApiError } from '../api/errors';
import type { IntelligencePort } from '../intelligence';
export function createUnavailableIntelligencePort():IntelligencePort {
 const unavailable=async():Promise<never>=>{throw new ApiError('CAPABILITY_UNAVAILABLE','Thống kê, xử lý dữ liệu và báo cáo đang chờ kết nối dịch vụ. Chưa có kết quả được xác nhận.',503);};
 return {load:unavailable,updateRequest:unavailable,processRequest:unavailable,downloadRequest:unavailable,previewReport:unavailable,createExport:unavailable,processExport:unavailable,reconcileExport:unavailable,downloadExport:unavailable};
}
