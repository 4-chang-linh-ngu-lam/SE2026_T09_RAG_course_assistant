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
    ans = defaultdict(list)
    for c in ch:
        if c['kieu'] == 'dap_an' and c['cau'] != '*':
            ans[(c['bo_de'], c['phan'], c['cau'])].append(c['text'])
    docs = []
    for c in ch:
        if not c['canonical'] or c['kieu'] == 'ma_tran':
            continue
        sol = ans.get((c['bo_de'], c['phan'], c['cau'])) if c['kieu'] == 'de' else None
        c['loi_giai'] = '\n'.join(sol) if sol else None
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
        mask = np.array([lop is None or d['lop'] == lop for d in self.docs])
        sc = self.bm.get_scores(tok(q)) * mask
        r_bm = [i for i in np.argsort(-sc)[:50] if mask[i]]
        if self.emb is None or mode == 'bm25':
            return [self.docs[i] for i in r_bm[:top]]
        qv = self.m.encode([q], normalize_embeddings=True)[0]
        ds = (self.emb @ qv) * mask - (1 - mask) * 9
        r_de = list(np.argsort(-ds)[:50])
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
