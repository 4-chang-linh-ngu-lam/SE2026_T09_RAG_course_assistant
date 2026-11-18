# DeepDoc OCR-VL trên Colab GPU

**Chạy full pipeline tài liệu:** dùng `deepdoc_full_rag_colab.ipynb`; xem [FULL_RAG.md](FULL_RAG.md). File OCR-VL bên dưới chỉ chạy riêng model và raw evidence.

Mở `deepdoc_ocr_vl_colab.ipynb` trong Colab, chọn GPU runtime, điền `RAG_DRIVE` và `INPUT_DRIVE` ở ô đầu tiên rồi Run all. `RAG_DRIVE` là thư mục có `idp` và `colab`; `INPUT_DRIVE` là một FILE PDF/ảnh thật trên Drive.

- `PAGES = None`: xử lý toàn bộ tài liệu.
- Model GPU nạp một lần cho cả tài liệu; render và inference từng trang tuần tự.
- `RESUME = True`: tiếp tục từ trang chưa có checkpoint hợp lệ khi chạy lại cùng input/cấu hình/phiên bản runner và package.
- PDF/cache trọng số được copy về `/content` để giảm I/O Drive. Sau lượt thành công, cache mới được lưu lại Drive.
- Venv Linux chạy trong `/content`; cache pip trên Drive. Ghim SentencePiece 0.2.1 và Protobuf 6.33.4; kiểm tra tokenizer/CUDA trước inference.
- Raw output từng trang được ghi atomically vào `MyDrive/deepdoc-colab-results/<source-hash>-<profile-hash>/`. Metadata giữ page/source/profile/weight hashes.
- Mỗi attempt có log, config, environment và RAM/VRAM trong thư mục `attempts`. Lỗi in ngay phần cuối log. Timeout hoặc Stop dừng process group, giữ trang đã hoàn thành.

Hai file `deepdoc_ocr_vl_colab.ipynb` và `ocr_vl_document.py` cần được đồng bộ lên Drive. Mở lại notebook mới trong Colab; tab cũ không tự cập nhật. Bản mới tạo output riêng so với notebook một worker mỗi trang trước đây.

MAX_NEW_TOKENS và độ phân giải là giới hạn tài nguyên, có thể làm nội dung dài bị cắt. SUCCESS chỉ chứng minh worker chạy xong và ghi raw output, không chứng nhận OCR hoàn chỉnh/đúng. Raw evidence chưa tự publish/index vào RAG.

Đã kiểm tra cú pháp notebook, CLI/lint runner và luồng render PDF thật ba trang với backend giả lập: một model initialization, ba inference calls; chạy resume không thêm inference calls. Chưa đo inference/tốc độ GPU của runner mới trên Colab. Lượt Colab cũ người dùng đã chạy OCR-VL thành công nhưng nạp lại model cho mỗi trang.

Nguồn: https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/PaddleOCR-VL.html ; https://paddlepaddle.github.io/FastDeploy/get_started/installation/nvidia_gpu/ ; https://research.google.com/colaboratory/faq.html
