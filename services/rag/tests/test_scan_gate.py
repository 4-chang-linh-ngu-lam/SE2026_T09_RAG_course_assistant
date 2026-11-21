# -*- coding: utf-8 -*-
"""Scan publication rules, on readings measured from SGK Toán 10 (PDF p17/p87/p100)."""

import pytest

from idp.ocr.backends.scan_gate import (
    compact_math,
    digits_agree,
    group_rows,
    line_confidence,
    numeric_signature,
)


@pytest.mark.parametrize(
    "book,latin,expected",
    [
        # rec.onnx writes "số" as "s6": a letter misread is not a number claim.
        ("Mot so tap con thuong dung cua tap s6 thucIR:",
         "Một số tập con thường dùng của tập số thực R:", True),
        ("Hay tim khoang tu phan vi cho mau s6 lieu nay.",
         "Hãy tìm khoảng tứ phân vị cho mẫu số liệu này.", True),
        # rec.onnx glues a number row; spacing is not a numeric claim.
        ("4345464140", "43   45   46   41   40", True),
        ("12", "12", True),
        # Prose with a list: separators and spacing differ, numbers agree.
        ("Nua so lieu ben trai la 7,8,11,13 gom 4 gia tri",
         "Nửa số liệu bên trái là 7, 8, 11, 13 gồm 4 giá trị", True),
        # A number must never be dropped or invented silently.
        ("Nua so lieu ben trai la 7,8,11,13 gom 4 gia tri",
         "Nửa số liệu bên trái là 7, 8, 13 gồm 4 giá trị", False),
        ("Luyentap 4.Hayghepmoi dong cotben trai",
         "12 luyện têp 4 Hãy ghép mỗi dòng ở cột bên trái", False),  # icon read as "12"
        ("12 2710912 9 10 11 10 14", "12 7 10 9 12 9 3 10 11 10 14", False),
        # Decimal separator is a numeric claim.
        ("9,5", "9.5", False),
        ("9, 5 kg", "95 kg", False),
        ("100kg", "kg", False),
        ("100kg", "10kg", False),
        ("-5", "5", False),
        ("12 34 kg", "1234 kg", False),
        ("1 23", "12 3", False),
        ("12 3", "123", False),
        ("a", "6", False),
    ],
)
def test_digits_agree(book, latin, expected):
    assert digits_agree(book, latin) is expected


def test_numeric_signature_ignores_spacing_but_keeps_separators():
    assert numeric_signature("7, 8,11") == "7,8,11"
    assert numeric_signature("43   45") == "4345"
    assert numeric_signature("9 , 5") == "9,5"
    assert numeric_signature("kết quả 14.") == "14"


def test_compact_math_unifies_dash_variants():
    assert compact_math("43 – 43 = 0") == compact_math("43-43=0") == compact_math("43 − 43 = 0")


def test_agreeing_number_row_takes_the_stronger_score():
    assert line_confidence("4345464140", 1.0, "43   45   46   41   40", 0.46) == 1.0
    # prose and disagreeing rows keep the Latin reader's own score
    assert line_confidence("Hay tim", 0.9, "Hãy tìm", 0.7) == 0.7
    assert line_confidence("12", 1.0, "13", 0.4) == 0.4


def box(x0, y0, x1, y1, text):
    return {"bbox": [x0, y0, x1, y1], "text": text}


def test_group_rows_rebuilds_printed_rows():
    cells = [
        box(700, 330, 750, 360, "75"),
        box(200, 332, 250, 358, "32"),
        box(450, 331, 500, 359, "59"),
        box(210, 390, 260, 420, "64"),
        box(700, 392, 750, 421, "68"),
    ]
    rows = group_rows(cells)
    assert [[c["text"] for c in row] for row in rows] == [["32", "59", "75"], ["64", "68"]]
