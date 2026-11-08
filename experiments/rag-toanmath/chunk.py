"""Chia Markdown đề thi thành chunk theo câu + gắn metadata -> chunks.jsonl.

Dùng: python chunk.py <thư_mục_md_1> [<thư_mục_md_2> ...] <chunks.jsonl>
Metadata lấy từ đường dẫn: Lớp N/<bộ đề>[/<file>].md
"""
import json
import os
import re
import sys
import unicodedata
from collections import Counter

Q_RE = re.compile(r'^\*\*(?:Câu|Bài)\s+(\d+)\.\*\*|^(?:Câu|Bài)\s+([IVX]+|\d+)\b', re.I)
PART_RE = re.compile(r'^\s*\**\s*(PHẦN|Phần)\s+([IVX]+|\d+)\b')
BOILER = re.compile(r'(Được thực hiện bởi|THCS\.TOANMATH|TOANMATH\.com)', re.I)


def fold(s):
    s = unicodedata.normalize('NFD', s.lower().replace('đ', 'd'))
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn')


def loai_de(slug):
    s = slug
    for key, val in [('giua-ki-1', 'Giữa HK1'), ('giua-ky-1', 'Giữa HK1'), ('giua-hoc-ki-1', 'Giữa HK1'),
                     ('giua-ki-2', 'Giữa HK2'), ('giua-ky-2', 'Giữa HK2'), ('giua-hoc-ki-2', 'Giữa HK2'),
                     ('cuoi-ki-1', 'HK1'), ('cuoi-ky-1', 'HK1'), ('hoc-ki-1', 'HK1'), ('hoc-ky-1', 'HK1'),
                     ('cuoi-ki-2', 'HK2'), ('cuoi-ky-2', 'HK2'), ('hoc-ki-2', 'HK2'), ('hoc-ky-2', 'HK2'),
                     ('hsg', 'HSG'), ('hoc-sinh-gioi', 'HSG'), ('giao-luu', 'HSG'), ('khao-sat', 'Khảo sát'),
                     ('thi-thu', 'Thi thử'), ('chuyen-de', 'Tài liệu'), ('tai-lieu', 'Tài liệu'), ('tom-tat', 'Tài liệu')]:
        if key in s:
            return val
    return 'Khác'


def meta_from_path(rel):
    parts = rel.replace('\\', '/').split('/')
    lop = int(re.search(r'(\d+)', parts[0]).group(1))
    slug = parts[1] if len(parts) == 3 else os.path.splitext(parts[1])[0]
    fname = os.path.splitext(parts[-1])[0]
    nf = fold(fname)
    if re.search(r'dap.?an|\bhdc\b|loi.?giai|huong.?dan', nf):
        kieu = 'dap_an'
    elif re.search(r'ma.?tran|dac.?ta', nf):
        kieu = 'ma_tran'
    else:
        kieu = 'de'
    nam = re.search(r'nam-(\d{4})-(\d{4})', slug)
    truong = re.search(r'(?:truong|cum-truong|chuyen)-(.+?)$', slug)
    return {
        'lop': lop, 'bo_de': slug, 'file': fname, 'kieu': kieu, 'loai_de': loai_de(slug),
        'nam_hoc': f'{nam.group(1)}-{nam.group(2)}' if nam else None,
        'truong': truong.group(1).replace('-', ' ') if truong else None,
    }


def split_questions(md):
    """-> list[(phan, cau, text)]; phần mở đầu (tiêu đề đề thi) bị bỏ."""
    out, phan, cur, cau = [], '', [], None
    def flush():
        if cau is not None and cur:
            out.append((phan, cau, '\n'.join(cur).strip()))
    for line in md.split('\n'):
        t = line.strip()
        if '|' in t[:2] or not t:
            if cau is not None:
                cur.append(line)
            continue
        mp = PART_RE.match(t)
        if mp and len(t) < 400:
            flush(); cur = []; cau = None
            phan = mp.group(2).upper()
            continue
        mq = Q_RE.match(t)
        if mq:
            flush()
            cau = (mq.group(1) or mq.group(2)).upper()
            cur = [line]
            continue
        if cau is not None:
            cur.append(line)
    flush()
    return out


def build(dirs):
    chunks, seen_de = [], {}
    for base in dirs:
        for dp, _, fs in os.walk(base):
            for f in sorted(fs):
                if not f.endswith('.md'):
                    continue
                path = os.path.join(dp, f)
                rel = os.path.relpath(path, base)
                m = meta_from_path(rel)
                md = open(path, encoding='utf-8').read()
                md = '\n'.join(l for l in md.split('\n') if not BOILER.search(l))
                qs = split_questions(md)
                if not qs:  # file đáp án dạng bảng/ma trận/tài liệu không có "Câu N": giữ nguyên 1 chunk
                    qs = [('', '*', md.strip())] if md.strip() else []
                if m['kieu'] == 'de':
                    seen_de.setdefault(m['bo_de'], m['file'])
                for phan, cau, text in qs:
                    cid = f"{m['lop']}/{m['bo_de']}/{m['file']}#{phan or '-'}-{cau}"
                    chunks.append({'id': cid, **m, 'phan': phan or None, 'cau': cau, 'text': text})
    for c in chunks:  # chỉ giữ 1 mã đề / bộ đề làm bản chính, tránh kết quả trùng
        c['canonical'] = c['kieu'] != 'de' or seen_de.get(c['bo_de']) == c['file']
    return chunks


if __name__ == '__main__':
    *dirs, out = sys.argv[1:]
    ch = build(dirs)
    with open(out, 'w', encoding='utf-8') as f:
        for c in ch:
            f.write(json.dumps(c, ensure_ascii=False) + '\n')
    print(len(ch), 'chunk;', sum(c['canonical'] for c in ch), 'chunk canonical')
    print('theo kieu:', Counter(c['kieu'] for c in ch))
    print('theo lop :', sorted(Counter(c['lop'] for c in ch).items()))
    L = sorted(len(c['text']) for c in ch)
    print('độ dài ký tự: min', L[0], 'median', L[len(L) // 2], 'p95', L[int(len(L) * .95)], 'max', L[-1])
