"""Word (.docx đề thi ToanMath) -> Markdown, công thức MathType -> LaTeX ($...$).

Dùng: python docx2md.py <file.docx | thư mục> <thư mục đầu ra>
Mỗi file ra <tên>.md + <tên>.json (thống kê số công thức, số lỗi chuyển đổi).
"""
import json
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

from mtef import CHARMAP, ole_to_latex

NS = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'm': 'http://schemas.openxmlformats.org/officeDocument/2006/math',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'o': 'urn:schemas-microsoft-com:office:office',
    'v': 'urn:schemas-microsoft-com:vml',
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'rel': 'http://schemas.openxmlformats.org/package/2006/relationships',
}
W = '{%s}' % NS['w']
M = '{%s}' % NS['m']
R = '{%s}' % NS['r']


def q(tag):
    p, t = tag.split(':')
    return '{%s}%s' % (NS[p], t)


class Doc:
    def __init__(self, path):
        self.z = zipfile.ZipFile(path)
        rels = ET.fromstring(self.z.read('word/_rels/document.xml.rels'))
        self.rels = {e.get('Id'): e.get('Target') for e in rels}
        self.stats = {'mathtype': 0, 'mathtype_fail': 0, 'omml': 0, 'images': 0, 'pict_images': 0, 'other_ole': 0}
        self.errors = []

    def ole(self, rid):
        target = self.rels.get(rid, '')
        name = 'word/' + target.lstrip('/').replace('word/', '') if not target.startswith('word/') else target
        try:
            latex = ole_to_latex(self.z.read(name))
            self.stats['mathtype'] += 1
            return latex
        except Exception as e:  # noqa: BLE001 - ghi lại để thống kê
            self.stats['mathtype_fail'] += 1
            self.errors.append(f'{target}: {e}')
            return None


# ------------------------------------------------------------ OMML (Equation gốc của Word) -> LaTeX, bản tối giản
def _omml_char(ch):
    if ch == '∘':  # ∘ dùng làm ký hiệu độ
        return r'\circ'
    s = CHARMAP.get(ord(ch))
    if s is None or ch.isascii() and ch not in '{}%#&_$\\':
        return ch
    return s + ' ' if s[-1].isalpha() else s


def omml(e):
    tag = e.tag[len(M):] if e.tag.startswith(M) else None
    kids = lambda name: e.find(M + name)
    sub = lambda name: omml(kids(name)) if kids(name) is not None else ''
    if tag == 't':
        return ''.join(_omml_char(ch) for ch in (e.text or ''))
    if tag == 'f':
        return r'\frac{' + sub('num') + '}{' + sub('den') + '}'
    if tag == 'sSup':
        return '{' + sub('e') + '}^{' + sub('sup') + '}'
    if tag == 'sSub':
        return '{' + sub('e') + '}_{' + sub('sub') + '}'
    if tag == 'sSubSup':
        return '{' + sub('e') + '}_{' + sub('sub') + '}^{' + sub('sup') + '}'
    if tag == 'rad':
        deg = sub('deg')
        return (r'\sqrt[' + deg + ']{' if deg else r'\sqrt{') + sub('e') + '}'
    if tag == 'd':
        pr = e.find(M + 'dPr')
        b, en = '(', ')'
        if pr is not None:
            bc, ec = pr.find(M + 'begChr'), pr.find(M + 'endChr')
            if bc is not None: b = bc.get(M + 'val') or '.'
            if ec is not None: en = ec.get(M + 'val') or '.'
        esc = {'{': r'\{', '}': r'\}'}
        inner = ','.join(omml(x) for x in e.findall(M + 'e'))
        return r'\left' + esc.get(b, b) + ' ' + inner + r' \right' + esc.get(en, en)
    if tag == 'bar':
        return r'\overline{' + sub('e') + '}'
    if tag == 'acc':
        pr = e.find(M + 'accPr')
        c = pr.find(M + 'chr') if pr is not None else None
        ch = c.get(M + 'val') if c is not None else '̂'  # mặc định của Word là dấu mũ
        cmd = {'̂': r'\widehat', '⃗': r'\overrightarrow', '→': r'\overrightarrow',
               '̅': r'\overline', '̄': r'\overline', '̃': r'\widetilde', '̇': r'\dot'}.get(ch, r'\widehat')
        return cmd + '{' + sub('e') + '}'
    if tag == 'eqArr':
        return r'\begin{array}{l}' + r' \\ '.join(omml(x) for x in e.findall(M + 'e')) + r'\end{array}'
    if tag and tag.endswith('Pr'):
        return ''
    return ''.join(omml(c) for c in e)


# ------------------------------------------------------------ đi qua thân văn bản
def run_parts(doc, el):
    """Sinh chuỗi Markdown cho các phần tử con của một đoạn (w:p)."""
    out = []
    for c in el.iter():
        t = c.tag
        if t == W + 't':
            out.append(c.text or '')
        elif t == W + 'tab':
            out.append(' ')
        elif t == W + 'br':
            out.append('  \n')
        elif t == q('o:OLEObject'):
            prog = c.get('ProgID', '')
            if prog.startswith('Equation.DSMT'):
                latex = doc.ole(c.get(R + 'id'))
                out.append(f'${latex}$' if latex is not None else '[CÔNG THỨC LỖI]')
            elif prog.startswith('Equation'):
                doc.stats['mathtype_fail'] += 1
                out.append('[CÔNG THỨC Equation3]')
            else:
                doc.stats['other_ole'] += 1
                out.append('[HÌNH]')
        elif t in (q('m:oMath'),):
            doc.stats['omml'] += 1
            out.append('$' + omml(c).strip() + '$')
        elif t == W + 'drawing' or (t == q('v:imagedata') and not _is_ole_preview(c)):
            doc.stats['images'] += 1
            out.append('[HÌNH]')
    return ''.join(out)


def _is_ole_preview(_):
    return True  # ảnh v:imagedata đi kèm OLE là ảnh xem trước của công thức -> bỏ


def walk(doc, body):
    lines = []
    for el in body:
        if el.tag == W + 'p':
            lines.append(para(doc, el))
        elif el.tag == W + 'tbl':
            lines.append(table(doc, el))
    md = '\n\n'.join(l for l in lines if l.strip())
    md = re.sub(r'\$\s*\$', '', md)
    md = re.sub(r'(?m)^(Câu|Bài)\s*(\d+)\s*[.:]', r'**\1 \2.**', md)
    return md + '\n'


def para(doc, p):
    # tránh đếm m:oMath lồng hai lần: nếu có oMathPara thì run_parts vẫn chỉ gặp mỗi oMath một lần
    skip = set()
    for om in p.iter(q('m:oMath')):
        for x in om.iter():
            if x is not om:
                skip.add(x)
    out, seen_math = [], set()
    for c in p.iter():
        if c in skip:
            continue
        if c.tag == q('m:oMath'):
            doc.stats['omml'] += 1
            out.append('$' + omml(c).strip() + '$')
        elif c.tag == W + 'pict' and c.find('.//' + q('o:OLEObject')) is None:
            doc.stats['pict_images'] += 1  # ảnh dán thẳng (thường là công thức chụp ảnh) -> mất nội dung
            out.append('[HÌNH]')
        elif c.tag in (W + 't', W + 'tab', W + 'br', q('o:OLEObject'), W + 'drawing'):
            # dùng lại run_parts cho phần tử lá
            holder = ET.Element('x'); holder.append(c)
            out.append(run_parts(doc, holder))
    return ''.join(out).strip()


def table(doc, tbl):
    rows = []
    for tr in tbl.findall(W + 'tr'):
        cells = []
        for tc in tr.findall(W + 'tc'):
            txt = ' '.join(para(doc, p) for p in tc.iter(W + 'p')).strip()
            cells.append(txt.replace('|', r'\|').replace('\n', ' '))
        rows.append(cells)
    if not rows:
        return ''
    n = max(len(r) for r in rows)
    rows = [r + [''] * (n - len(r)) for r in rows]
    out = ['| ' + ' | '.join(rows[0]) + ' |', '|' + '---|' * n]
    out += ['| ' + ' | '.join(r) + ' |' for r in rows[1:]]
    return '\n'.join(out)


def convert(path, out_dir):
    doc = Doc(path)
    body = ET.fromstring(doc.z.read('word/document.xml')).find(W + 'body')
    md = walk(doc, body)
    base = os.path.splitext(os.path.basename(path))[0]
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, base + '.md'), 'w', encoding='utf-8') as f:
        f.write(md)
    info = {'file': path, **doc.stats, 'errors': doc.errors[:20]}
    with open(os.path.join(out_dir, base + '.json'), 'w', encoding='utf-8') as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    return info


if __name__ == '__main__':
    import collections
    src, dst = sys.argv[1], sys.argv[2]
    if src.lower().endswith('.docx'):
        jobs = [(src, dst)]
    else:  # giữ cấu trúc Lớp N/<bộ đề>/
        jobs = [(os.path.join(dp, f), os.path.join(dst, os.path.relpath(dp, src)))
                for dp, _, fs in os.walk(src) for f in fs if f.lower().endswith('.docx')]
    total = collections.Counter()
    for f, out in jobs:
        i = convert(f, out)
        total.update({k: v for k, v in i.items() if isinstance(v, int)})
        total['files'] += 1
        print(f"{i['mathtype']:5} ok {i['mathtype_fail']:3} lỗi {i['omml']:4} omml {i['pict_images']:3} ảnh-dán  {os.path.basename(f)}")
    print('TỔNG:', dict(total))
