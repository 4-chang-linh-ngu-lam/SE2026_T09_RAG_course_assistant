from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

ERROR_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    503: "SERVICE_UNAVAILABLE",
}

STATUS_MESSAGES = {
    400: "Thông tin gửi lên chưa hợp lệ. Vui lòng kiểm tra lại.",
    401: "Phiên đăng nhập không hợp lệ hoặc đã hết hạn. Vui lòng đăng nhập lại.",
    403: "Bạn không có quyền thực hiện thao tác này.",
    404: "Không tìm thấy nội dung bạn yêu cầu.",
    409: "Dữ liệu vừa thay đổi hoặc yêu cầu không còn phù hợp. Vui lòng tải lại rồi thử lại.",
    422: "Thông tin chưa hợp lệ. Vui lòng kiểm tra các trường đã nhập.",
    429: "Bạn thao tác quá nhanh. Vui lòng chờ một chút rồi thử lại.",
    500: "Hệ thống đang gặp sự cố. Vui lòng thử lại sau.",
    503: "Dịch vụ đang tạm thời gián đoạn. Vui lòng thử lại sau.",
}

APP_ERROR_MESSAGES = {
    "Identity lookup unavailable": "Chưa thể xác minh tài khoản lúc này. Vui lòng thử lại sau.",
    "Authentication unavailable": "Chức năng xác thực đang tạm thời gián đoạn. Vui lòng thử lại sau.",
    "Internal authentication unavailable": "Chưa thể xác minh quyền truy cập lúc này. Vui lòng thử lại sau.",
    "Notification audience unavailable": "Chưa thể xác định người nhận thông báo. Vui lòng thử lại sau.",
    "Email delivery unavailable": "Chưa thể gửi email lúc này. Vui lòng thử lại sau.",
    "Idempotency store unavailable": "Hệ thống chưa thể xác nhận yêu cầu trước đó. Vui lòng kiểm tra trạng thái rồi thử lại.",
    "Idempotency key payload mismatch": "Mã xác nhận này đã được dùng cho nội dung khác. Hãy kiểm tra trạng thái trước khi gửi yêu cầu mới.",
    "Rate limiter unavailable": "Hệ thống chưa thể xác nhận yêu cầu lúc này. Vui lòng thử lại sau.",
    "Invalid cursor": "Liên kết trang dữ liệu không còn hợp lệ. Vui lòng tải lại trang.",
    "Unknown Admin reason code": "Vui lòng chọn lý do quản trị viên hợp lệ.",
    "Unknown class action": "Thao tác với lớp chưa hợp lệ. Vui lòng tải lại trang rồi thử lại.",
    "X-Admin-Reason is required": "Vui lòng chọn lý do trước khi xác nhận thay đổi.",
    "Invalid or oversized student import file": "Tệp danh sách học sinh không đúng định dạng hoặc vượt quá dung lượng cho phép.",
    "Invalid time interval": "Thời gian kết thúc cần sau thời gian bắt đầu.",
    "Invalid event interval": "Thời gian kết thúc cần sau thời gian bắt đầu.",
    "Datetime must include a timezone": "Thời gian cần có múi giờ rõ ràng.",
    "from must be before to": "Thời điểm bắt đầu cần trước thời điểm kết thúc.",
    "Invalid Learning deadline": "Thời hạn học tập chưa hợp lệ.",
    "Cannot remove or lock the last active administrator": "Không thể khóa hoặc gỡ quyền của quản trị viên đang hoạt động cuối cùng.",
    "Invalid request origin": "Yêu cầu không đến từ trang Lumi hợp lệ.",
    "Unknown account type": "Loại tài khoản chưa hợp lệ.",
    "Unknown account role": "Vai trò tài khoản chưa hợp lệ.",
    "Unknown account status": "Trạng thái tài khoản chưa hợp lệ.",
    "Account changed; reload before updating": "Tài khoản vừa thay đổi. Hãy tải lại trang rồi thử lại.",
    "An account cannot return to pending verification": "Tài khoản đã xử lý không thể quay lại trạng thái chờ kích hoạt.",
    "Staff roles require staff credentials": "Vai trò nhân sự cần địa chỉ email đã xác minh.",
    "Student credential migration required": "Tài khoản học sinh cần được gán tên đăng nhập trước khi dùng chức năng này.",
    "Account activation required": "Tài khoản chưa được kích hoạt. Hãy hoàn tất kích hoạt trước khi đăng nhập.",
    "Credential verification required": "Cần xác minh tài khoản trước khi thực hiện thao tác này.",
    "Administrator identity verification required": "Quản trị viên cần xác minh danh tính theo quy trình của nhà trường.",
    "Manual fulfillment confirmation required": "Hãy xác nhận đã thực hiện thủ công trước khi hoàn tất yêu cầu.",
    "Data request is already final": "Yêu cầu này đã được xử lý xong và không thể thay đổi.",
    "Roster changed; preview the change again": "Danh sách học sinh đã thay đổi. Hãy xem trước lại trước khi xác nhận.",
    "Roster changed; preview the import again": "Danh sách học sinh đã thay đổi. Hãy xem trước tệp nhập lại trước khi xác nhận.",
    "Roster changed; preview the transfer again": "Danh sách học sinh đã thay đổi. Hãy xem trước lại việc chuyển lớp trước khi xác nhận.",
    "Import preview expired": "Bản xem trước đã hết hạn. Hãy tải lại tệp để tiếp tục.",
    "Accounts changed; preview the import again": "Danh sách tài khoản đã thay đổi. Hãy xem trước lại trước khi xác nhận.",
    "Class changed; reload before updating teachers": "Thông tin lớp đã thay đổi. Hãy tải lại trang rồi cập nhật lại phân công.",
    "Select a different destination homeroom": "Vui lòng chọn một lớp hành chính khác.",
    "Homerooms must share a year and grade": "Chỉ có thể chuyển giữa các lớp hành chính cùng khối và năm học.",
    "Student already belongs to destination homeroom": "Học sinh đã thuộc lớp hành chính được chọn.",
    "Student already enrolled in destination": "Học sinh đã có trong lớp được chọn.",
    "Homeroom must match year and grade": "Lớp hành chính cần cùng khối và năm học với lớp môn học.",
    "AUTO enrollment requires a homeroom": "Ghi danh tự động cần gắn với một lớp hành chính.",
    "A homeroom is required": "Vui lòng chọn lớp hành chính trước khi tiếp tục.",
    "Class creation conflicts with current data": "Thông tin lớp vừa thay đổi. Hãy kiểm tra lại rồi thử tạo lớp.",
    "Enrollment preview is stale or missing": "Bản xem trước ghi danh đã hết hạn. Hãy tạo bản xem trước mới.",
    "Only AUTO classes can sync a roster": "Chỉ lớp tự động ghi danh mới có thể đồng bộ danh sách.",
    "Class or roster changed; preview the sync again": "Lớp hoặc danh sách học sinh đã thay đổi. Hãy xem trước đồng bộ lại.",
    "Switch to MANUAL enrollment before exceptions": "Hãy chuyển lớp sang ghi danh thủ công trước khi thêm trường hợp riêng.",
    "Class changed; preview the roster again": "Thông tin lớp đã thay đổi. Hãy xem trước danh sách lại trước khi xác nhận.",
    "Only MANUAL classes accept a managed roster": "Chỉ lớp ghi danh thủ công mới nhận danh sách do quản trị viên quản lý.",
    "Select a different destination class": "Vui lòng chọn một lớp môn học khác.",
    "AUTO transfers follow the homeroom roster": "Lớp tự động ghi danh đồng bộ theo lớp hành chính. Hãy cập nhật danh sách lớp hành chính.",
    "Transfer requires the same subject and term": "Chỉ có thể chuyển giữa các lớp cùng môn học và học kỳ.",
    "Class changed; reload before changing its status": "Thông tin lớp đã thay đổi. Hãy tải lại trang trước khi lưu trạng thái.",
    "Archived classes are read-only": "Lớp đã lưu trữ nên hiện chỉ có thể xem.",
    "Course code already exists": "Mã môn học đã được sử dụng.",
    "Homeroom already exists": "Lớp hành chính này đã tồn tại.",
    "Expected a Student account": "Tài khoản được chọn không phải tài khoản học sinh.",
    "Expected an active lecturer": "Giáo viên được chọn không ở trạng thái hoạt động.",
    "Email already registered": "Email này đã được dùng cho một tài khoản khác.",
    "Invalid verification token": "Liên kết xác minh không hợp lệ hoặc đã hết hạn. Hãy yêu cầu gửi lại.",
    "Invalid reset token": "Liên kết đặt lại mật khẩu không hợp lệ hoặc đã hết hạn. Hãy yêu cầu cấp lại.",
    "Invalid invitation token": "Lời mời không hợp lệ hoặc đã hết hạn. Hãy liên hệ quản trị viên nhà trường để được gửi lại.",
    "Invalid or expired activation code": "Mã kích hoạt không hợp lệ hoặc đã hết hạn. Hãy liên hệ quản trị viên nhà trường.",
    "Invalid or expired token": "Mã xác thực không hợp lệ hoặc đã hết hạn. Hãy yêu cầu cấp mã mới.",
    "Only a pending staff invitation can be reissued": "Chỉ có thể gửi lại lời mời cho tài khoản nhân sự đang chờ kích hoạt.",
    "Invitation could not be reissued": "Chưa thể cấp lại lời mời lúc này. Vui lòng thử lại sau.",
    "Username already assigned": "Tên đăng nhập này đã được sử dụng.",
    "Username already assigned to this account": "Tài khoản đã có tên đăng nhập này.",
    "Legacy account verification required": "Cần xác minh tài khoản cũ theo quy trình của nhà trường trước khi tiếp tục.",
    "Assign a username before issuing a code": "Hãy gán tên đăng nhập cho học sinh trước khi cấp mã.",
    "Account cannot receive a code in its current state": "Tài khoản hiện không thể nhận mã. Hãy kiểm tra trạng thái tài khoản.",
    "Expected a Student account without staff roles": "Thao tác này chỉ dành cho tài khoản học sinh không có vai trò nhân sự.",
    "Student accounts must be provisioned by an administrator": "Tài khoản học sinh do quản trị viên nhà trường cấp.",
    "Idempotency-Key is not supported for one-time code operations": "Không thể tự động gửi lại thao tác cấp mã. Hãy kiểm tra trạng thái hoặc liên hệ quản trị viên.",
    "UNAUTHENTICATED": STATUS_MESSAGES[401],
    "FORBIDDEN": STATUS_MESSAGES[403],
    "NOT_FOUND": STATUS_MESSAGES[404],
    "BAD_REQUEST": STATUS_MESSAGES[400],
    "CONFLICT": STATUS_MESSAGES[409],
    "VALIDATION_ERROR": STATUS_MESSAGES[422],
    "RATE_LIMITED": STATUS_MESSAGES[429],
    "INTERNAL_ERROR": STATUS_MESSAGES[500],
    "SERVICE_UNAVAILABLE": STATUS_MESSAGES[503],
}

VIETNAMESE_APP_ERROR_MESSAGES = {
    "Lớp đã lưu trữ": "Lớp đã được lưu trữ nên hiện chỉ có thể xem.",
}


class ErrorDetail(BaseModel):
    code: str
    message: str
    correlation_id: UUID


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


class AppError(HTTPException):
    def __init__(self, status_code: int, message: str | None = None):
        super().__init__(status_code, message or ERROR_CODES.get(status_code, "HTTP_ERROR"))


def error_response(request: Request, status: int, message: str, headers=None) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", str(uuid4()))
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": ERROR_CODES.get(status, "HTTP_ERROR"),
                "message": message,
                "correlation_id": correlation_id,
            }
        },
        headers={
            **(headers or {}),
            "X-Correlation-ID": correlation_id,
            "Cache-Control": "no-store",
        },
    )


def _public_error_message(status: int, detail: str | None = None) -> str:
    if detail:
        localized = APP_ERROR_MESSAGES.get(detail) or VIETNAMESE_APP_ERROR_MESSAGES.get(detail)
        if localized:
            return localized
    return STATUS_MESSAGES.get(status, "Đã xảy ra lỗi. Vui lòng thử lại.")


def register_error_handlers(app: FastAPI) -> None:
    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next):
        try:
            correlation_id = str(UUID(request.headers.get("X-Correlation-ID", "")))
        except ValueError:
            correlation_id = str(uuid4())
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        # Never expose arbitrary exception detail or resource information for hidden resources.
        detail = str(exc.detail) if isinstance(exc, AppError) and exc.status_code != 404 else None
        message = _public_error_message(exc.status_code, detail)
        return error_response(request, exc.status_code, message, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Pydantic errors can include passwords/tokens in the input field.
        return error_response(request, 422, STATUS_MESSAGES[422])

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        return error_response(request, 500, STATUS_MESSAGES[500])
