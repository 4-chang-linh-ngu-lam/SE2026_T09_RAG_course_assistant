"""Truy hồi thử: BM25 + bge-m3 (dense) + RRF. Chỉ dùng chunk 'canonical' của đề thi.

Dùng:
  python retrieve.py build            # tạo embeddings.npy (CPU, vài phút)
  python retrieve.py "câu hỏi" [lop]  # truy vấn; lop tuỳ chọn để lọc
"""
import json
import os
import re
import sys
from collections import defaultdict

import numpy as np
from rank_bm25 import BM25Okapi

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = 'BAAI/bge-m3'
RERANKER = 'BAAI/bge-reranker-v2-m3'
RERANK_POOL = 20


def load():
    ch = [json.loads(l) for l in open(os.path.join(HERE, 'chunks.jsonl'), encoding='utf-8')]
    import answer_keys as AK
    de_files = defaultdict(set)
    for c in ch:
        if c['kieu'] == 'de':
            de_files[c['bo_de']].add(c['file'])
    ans = defaultdict(list)
    for c in ch:
        if c['kieu'] == 'dap_an' and c['cau'] != '*':
            ans[(c['bo_de'], c['phan'], c['cau'])].append((AK.code_of(c['file']), c['text']))

    def solution_for(c):
        """Chỉ ghép lời giải khi chắc cùng mã đề: mã khớp, hoặc file đáp án không ghi mã và bộ đề chỉ có 1 file đề."""
        out = []
        code = AK.code_of(c['file'])
        for acode, text in ans.get((c['bo_de'], c['phan'], c['cau']), []):
            if (acode and acode == code) or (acode is None and len(de_files[c['bo_de']]) == 1):
                out.append(text)
        return out
    keys = AK.build(ch)
    docs = []
    for c in ch:
        if not c['canonical'] or c['kieu'] == 'ma_tran':
            continue
        sol = solution_for(c) if c['kieu'] == 'de' else None
        c['loi_giai'] = '\n'.join(sol) if sol else None
        c['dap_an_tn'] = None
        if c['kieu'] == 'de' and not sol and c['phan'] in (None, 'I', '1') and c['cau'].isdigit() and AK.is_mcq(c['text']):
            k = keys.get((c['bo_de'], AK.code_of(c['file']) or 'file:' + c['file']))
            if k is None and len(de_files[c['bo_de']]) == 1:  # bảng không ghi mã đề: chỉ tin khi bộ đề có 1 file đề
                k = keys.get((c['bo_de'], None))
            hit = k.get(int(c['cau'])) if k else None
            if hit:
                c['dap_an_tn'] = hit[0]
                c['loi_giai'] = f"Đáp án trắc nghiệm (theo file đáp án «{hit[1]}»): {hit[0]}"
        head = f"Lớp {c['lop']} | {c['loai_de']} | {c['nam_hoc'] or ''} | {c['truong'] or ''}"
        c['index_text'] = head + '\n' + c['text'] + (('\n' + c['loi_giai']) if c['loi_giai'] else '')
        docs.append(c)
    return docs


def tok(s):
    s = s.lower()
    s = re.sub(r'\\([a-z]+)', r' \1 ', s)           # lệnh LaTeX -> từ (frac, sqrt, ...)
    return re.findall(r'\w+', s)


def bm25_rank(bm, query, k):
    sc = bm.get_scores(tok(query))
    return list(np.argsort(-sc)[:k])


def rrf(rankings, k=60, top=10):
    s = defaultdict(float)
    for r in rankings:
        for i, d in enumerate(r):
            s[d] += 1 / (k + i + 1)
    return [d for d, _ in sorted(s.items(), key=lambda x: -x[1])[:top]]


def build():
    from sentence_transformers import SentenceTransformer
    docs = load()
    m = SentenceTransformer(MODEL, device='cpu')
    m.max_seq_length = 512
    texts = [d['index_text'][:2000] for d in docs]
    order = np.argsort([len(t) for t in texts])  # sắp theo độ dài để batch hiệu quả
    emb = np.zeros((len(texts), m.get_sentence_embedding_dimension()), dtype=np.float32)
    B = 16
    for i in range(0, len(order), B):
        idx = order[i:i + B]
        emb[idx] = m.encode([texts[j] for j in idx], normalize_embeddings=True)
        if (i // B) % 20 == 0:
            print(f'{i}/{len(order)}', flush=True)
    np.save(os.path.join(HERE, 'embeddings.npy'), emb)
    print('xong', emb.shape)


class Retriever:
    def __init__(self, dense=True):
        self.docs = load()
        self.bm = BM25Okapi([tok(d['index_text']) for d in self.docs])
        self.emb = None
        p = os.path.join(HERE, 'embeddings.npy')
        if dense and os.path.exists(p):
            from sentence_transformers import SentenceTransformer
            self.emb = np.load(p)
            self.m = SentenceTransformer(MODEL, device='cpu')

    def search(self, q, lop=None, top=5, mode='hybrid'):
        # Chỉ xếp hạng trong tập được phép (fail closed): không bao giờ lấy chunk ngoài bộ lọc để "lấp chỗ".
        allowed = np.flatnonzero([lop is None or d['lop'] == lop for d in self.docs])
        if allowed.size == 0:
            return []
        sc = self.bm.get_scores(tok(q))[allowed]
        r_bm = [int(i) for i in allowed[np.argsort(-sc)[:50]]]
        if self.emb is None or mode == 'bm25':
            return [self.docs[i] for i in r_bm[:top]]
        qv = self.m.encode([q], normalize_embeddings=True)[0]
        ds = self.emb[allowed] @ qv
        r_de = [int(i) for i in allowed[np.argsort(-ds)[:50]]]
        if mode == 'dense':
            return [self.docs[i] for i in r_de[:top]]
        if mode != 'rerank':
            return [self.docs[i] for i in rrf([r_bm, r_de], top=top)]
        cand = [self.docs[i] for i in rrf([r_bm, r_de], top=RERANK_POOL)]
        scores = self.reranker().predict([(q, d['index_text'][:1500]) for d in cand], batch_size=8)
        for d, s in zip(cand, scores):
            d['score'] = float(s)
        return sorted(cand, key=lambda d: -d['score'])[:top]

    def reranker(self):
        if not hasattr(self, '_rr'):
            from sentence_transformers import CrossEncoder
            self._rr = CrossEncoder(RERANKER, device='cpu', max_length=512)
        return self._rr


if __name__ == '__main__':
    if sys.argv[1] == 'build':
        build()
    else:
        R = Retriever()
        lop = int(sys.argv[2]) if len(sys.argv) > 2 else None
        for d in R.search(sys.argv[1], lop):
            print(f"[{d['id']}]\n  {d['text'][:200]!r}\n  lời giải: {'có' if d['loi_giai'] else 'không'}")
