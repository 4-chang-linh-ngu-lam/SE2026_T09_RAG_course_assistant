import type { ClassroomAdminPort } from '../classroom-admin';
import { ApiError } from '../api/errors';
const unavailable = async (): Promise<never> => { throw new ApiError('CAPABILITY_UNAVAILABLE', 'Quản lý lớp học chưa được kết nối. Vui lòng thử lại khi nhà trường mở dịch vụ.', 503); };
export function createUnavailableClassroomAdminPort(): ClassroomAdminPort { return { load: unavailable, saveCatalog: unavailable, createHomeroom: unavailable, previewHomeroomRoster: unavailable, confirmHomeroomRoster: unavailable, createClass: unavailable, saveClassSettings: unavailable, previewEnrollment: unavailable, confirmEnrollment: unavailable, reconcileEnrollment: unavailable, changeLifecycle: unavailable }; }
