"""Đo truy hồi trên eval_set.jsonl: Recall@1/5, MRR cho câu có đáp án;
với câu ngoài dữ liệu (gold=null) xem điểm tương đồng dense cao nhất để chọn ngưỡng từ chối."""
import json
import os
import sys

import numpy as np

from retrieve import Retriever

HERE = os.path.dirname(os.path.abspath(__file__))
items = [json.loads(l) for l in open(os.path.join(HERE, 'eval_set.jsonl'), encoding='utf-8')]
R = Retriever()
ids = [d['id'] for d in R.docs]
missing = [it['gold'] for it in items if it['gold'] and it['gold'] not in ids]
assert not missing, missing

pos = [it for it in items if it['gold']]
neg = [it for it in items if not it['gold']]
for mode in ['bm25', 'dense', 'hybrid', 'rerank']:
    r1 = r5 = mrr = 0
    fails = []
    for it in pos:
        got = [d['id'] for d in R.search(it['q'], it['lop'], top=10, mode=mode)]
        if it['gold'] in got:
            rank = got.index(it['gold']) + 1
            mrr += 1 / rank
            r1 += rank == 1
            r5 += rank <= 5
        else:
            fails.append(it['q'])
    n = len(pos)
    print(f'{mode:6} R@1 {r1/n:.0%}  R@5 {r5/n:.0%}  MRR {mrr/n:.2f}  (n={n})  trượt top10: {len(fails)}')
    if mode in ('hybrid', 'rerank'):
        for q in fails:
            print('   trượt:', q)


def top_sim(q, lop):
    qv = R.m.encode([q], normalize_embeddings=True)[0]
    mask = np.array([d['lop'] == lop for d in R.docs])
    return float(((R.emb @ qv) * mask).max())


ps = [top_sim(it['q'], it['lop']) for it in pos]
ns = [top_sim(it['q'], it['lop']) for it in neg]
print(f'\nđiểm dense top1 — có trong dữ liệu: min {min(ps):.3f} median {np.median(ps):.3f}')
print(f'                   ngoài dữ liệu : max {max(ns):.3f} median {np.median(ns):.3f}')
for t in [0.5, 0.55, 0.6, 0.65]:
    keep = sum(s >= t for s in ps) / len(ps)
    rej = sum(s < t for s in ns) / len(ns)
    print(f'  ngưỡng {t}: giữ đúng {keep:.0%} câu có dữ liệu, từ chối đúng {rej:.0%} câu ngoài dữ liệu')

# Ngưỡng từ chối theo điểm reranker (logit của cross-encoder)
ps = [R.search(it['q'], it['lop'], top=1, mode='rerank')[0]['score'] for it in pos]
ns = [R.search(it['q'], it['lop'], top=1, mode='rerank')[0]['score'] for it in neg]
print(f'\nđiểm reranker top1 — có dữ liệu: min {min(ps):.2f} median {np.median(ps):.2f}')
print(f'                     ngoài dữ liệu: max {max(ns):.2f} median {np.median(ns):.2f}')
for t in sorted(set(round(x, 1) for x in np.linspace(min(ns), max(ps), 8))):
    keep = sum(s >= t for s in ps) / len(ps)
    rej = sum(s < t for s in ns) / len(ns)
    print(f'  ngưỡng {t:.1f}: giữ đúng {keep:.0%}, từ chối đúng {rej:.0%}')
