class DocumentError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message
        super().__init__(code)


def denied():
    raise DocumentError(403, "FORBIDDEN", "Bạn không còn quyền truy cập nguồn này.")


def conflict(message="Dữ liệu đã thay đổi. Hãy tải lại trước khi thực hiện."):
    raise DocumentError(409, "CONFLICT", message)


def missing():
    raise DocumentError(404, "NOT_FOUND", "Không tìm thấy nội dung.")
