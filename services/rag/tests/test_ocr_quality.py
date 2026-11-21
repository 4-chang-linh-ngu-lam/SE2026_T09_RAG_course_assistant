"""Regression coverage for hOCR line extraction."""

from idp.ocr.fast import parse_hocr_lines


def test_hocr_keeps_header_and_caption_as_separate_lines():
    def line(kind, text, y):
        return (
            f'<span class="ocr_{kind}" title="bbox 0 {y} 90 {y + 12}">'
            f'<span class="ocrx_word" title="bbox 1 {y} 70 {y + 12}; x_wconf 99">{text}</span>'
            "</span>"
        )

    hocr = (
        line("header", "Header", 0)
        + line("line", "Body", 20)
        + line("caption", "Caption", 40)
    )
    assert [item["text"] for item in parse_hocr_lines(hocr)] == [
        "Header",
        "Body",
        "Caption",
    ]
