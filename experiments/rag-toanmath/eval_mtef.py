"""Đánh giá bộ chuyển MathType -> LaTeX trên toàn bộ thư mục .docx.

- Tỉ lệ parse thành công.
- Với công thức có chú thích "TeX Input Language" (TeX người soạn đã gõ): so sánh sau chuẩn hoá.
Dùng: python eval_mtef.py <thư mục docx> [số mẫu lệch in ra]
"""
import collections
import os
import random
import re
import sys
import zipfile

from mtef import ole_to_latex

EQUIV = [
    (r'\dfrac', r'\frac'), (r'\tfrac', r'\frac'), (r'\cfrac', r'\frac'), (r'\left', ''), (r'\right', ''),
    (r'\vec', r'\overrightarrow'), (r'\bar', r'\overline'), (r'\widehat', r'\hat'),
    (r'\cdots', r'\ldots'), (r'\dots', r'\ldots'), (r'\implies', r'\Rightarrow'), (r'\iff', r'\Leftrightarrow'),
    (r'\qquad', ''), (r'\quad', ''), (r'\lvert', '|'), (r'\rvert', '|'), (r'\vert', '|'),
    (r'\begin{cases}', r'\{\begin{matrix}'), (r'\end{cases}', r'\end{matrix}'),
    (r'\begin{array}{l}', r'\begin{matrix}'), (r'\end{array}', r'\end{matrix}'),
    (r'\varnothing', r'\emptyset'), (r'\displaystyle', ''), (r'\cdot', '.'),
    (r'\,', ''), (r'\;', ''), (r'\ ', ''), ('~', ''),
]


def norm(s):
    for a, b in EQUIV:
        s = s.replace(a, b)
    s = re.sub(r'\\(text|mathrm|operatorname)\{([^{}]*)\}', r'\2', s)
    s = re.sub(r'\\(leqslant|leq)(?![a-zA-Z])', r'\\le', s)
    s = re.sub(r'\\(geqslant|geq)(?![a-zA-Z])', r'\\ge', s)
    s = re.sub(r'\\neq(?![a-zA-Z])', r'\\ne', s)
    s = re.sub(r'\\to(?![a-zA-Z])', r'\\rightarrow', s)
    return re.sub(r'[\s{}.]', '', s)


def main(root, show=15):
    st = collections.Counter()
    bad, errs = [], collections.Counter()
    for dp, _, fs in os.walk(root):
        for f in fs:
            if not f.lower().endswith('.docx'):
                continue
            z = zipfile.ZipFile(os.path.join(dp, f))
            for n in z.namelist():
                if not n.startswith('word/embeddings/oleObject'):
                    continue
                st['ole'] += 1
                try:
                    latex, tex = ole_to_latex(z.read(n), with_annot=True)
                except Exception as e:  # noqa: BLE001
                    st['fail'] += 1
                    errs[str(e)[:40]] += 1
                    continue
                st['ok'] += 1
                if tex:
                    st['has_tex'] += 1
                    if norm(latex) == norm(tex):
                        st['match'] += 1
                    else:
                        bad.append((tex, latex, f))
    print(dict(st))
    if st['ole']:
        print(f"parse ok: {st['ok'] / st['ole']:.2%}")
    if st['has_tex']:
        print(f"khớp TeX gốc: {st['match'] / st['has_tex']:.2%} trên {st['has_tex']} công thức có TeX gốc")
    print('lỗi:', errs.most_common(8))
    random.seed(0)
    for tex, latex, f in random.sample(bad, min(show, len(bad))):
        print('-' * 60)
        print('GỐC :', tex)
        print('DỰNG:', latex)


if __name__ == '__main__':
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 15)
