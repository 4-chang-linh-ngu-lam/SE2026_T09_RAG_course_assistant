"""Đọc bảng đáp án trắc nghiệm (A/B/C/D) từ chunk đáp án dạng bảng.

4 kiểu bảng gặp trong dữ liệu:
  A) hàng = mã đề, cột = câu     | Mã đề | 1 | 2 | ... /  | 1101 | D | B | ...
  B) hàng = câu, cột = mã đề     | Câu\\Mã đề | 1101 | 1102 | /  | 1 | B | A |
  C) 2 cột không mã đề           | Câu | Đáp án | /  | 1 | B |
  D) hàng câu / hàng đáp án xen kẽ | Câu | 1 | 2 | ... /  | Đáp án | B | B | ...   (hoặc | Câu 1 | Câu 2 | / | B | C |)
Trả về {(bo_de, ma_de|None): {so_cau: 'A'..'D'}}.
"""
import re
from collections import defaultdict

LETTER = re.compile(r'^[ABCD]$')
CODE = re.compile(r'^\d{3,4}$')


def _int(s):
    m = re.fullmatch(r'(?:câu\s*)?(\d{1,2})\.?', s.strip(), re.I)
    return int(m.group(1)) if m else None


def tables(md):
    cur = []
    for line in md.split('\n'):
        if line.startswith('|'):
            if re.fullmatch(r'\|(?:-+\|)+', line.strip()):
                continue
            cur.append([c.strip() for c in line.strip().strip('|').split('|')])
        elif cur:
            yield cur
            cur = []
    if cur:
        yield cur


def parse_table(rows):
    """-> list[(ma_de|None, cau, letter)]"""
    out = []
    for i, row in enumerate(rows):
        rest = row[1:]
        # A: header các số câu, các hàng sau bắt đầu bằng mã đề
        if rest and all(_int(c) for c in rest if c):
            nums = [_int(c) for c in rest]
            for nxt in rows[i + 1:]:
                if CODE.match(nxt[0]):
                    for n, v in zip(nums, nxt[1:]):
                        if n and LETTER.match(v):
                            out.append((nxt[0], n, v))
                elif re.match(r'đáp\s*án', nxt[0], re.I):  # D: hàng "Đáp án"
                    for n, v in zip(nums, nxt[1:]):
                        if n and LETTER.match(v):
                            out.append((None, n, v))
                    break
                else:
                    break
        # D': header "Câu 1 | Câu 2 ..." (cả ô đầu), hàng sau là chữ cái
        if all(re.fullmatch(r'câu\s*\d{1,2}', c, re.I) for c in row if c) and i + 1 < len(rows):
            for c, v in zip(row, rows[i + 1]):
                if LETTER.match(v):
                    out.append((None, _int(c), v))
        # B: header các mã đề
        codes = [c if CODE.match(c) else None for c in rest]
        if rest and sum(1 for c in codes if c) >= 1 and all(c or not x for c, x in zip(codes, rest)):
            for nxt in rows[i + 1:]:
                n = _int(nxt[0])
                if n is None:
                    break
                for code, v in zip(codes, nxt[1:]):
                    if code and LETTER.match(v):
                        out.append((code, n, v))
        # C: | Câu | Đáp án |
        if len(row) == 2 and re.match(r'câu', row[0], re.I) and re.match(r'đáp\s*án', row[1], re.I):
            for nxt in rows[i + 1:]:
                n = _int(nxt[0])
                if n is None or len(nxt) < 2:
                    break
                if LETTER.match(nxt[1]):
                    out.append((None, n, nxt[1]))
    return out


def build(chunks):
    keys = defaultdict(dict)
    for c in chunks:
        if c['kieu'] not in ('dap_an', 'de'):
            continue
        for t in tables(c['text']):
            found = parse_table(t)
            if c['kieu'] == 'de' and len(found) < 4:  # trong file đề: chỉ tin bảng đáp án thật (>=4 câu)
                continue
            for code, n, v in found:
                if code is None and c['kieu'] == 'de':
                    code = code_of(c['file']) or ('file:' + c['file'])  # bảng nằm ngay trong file đề đó
                keys[(c['bo_de'], code)].setdefault(n, (v, c['file']))
    return keys


def code_of(fname):
    runs = re.findall(r'\d{3,4}', fname)
    runs = [r for r in runs if not re.fullmatch(r'20\d\d', r)]  # bỏ năm
    return runs[-1] if runs else None


def is_mcq(text):
    return all(re.search(rf'(^|\s|\|){x}\.', text) for x in 'ABCD')
