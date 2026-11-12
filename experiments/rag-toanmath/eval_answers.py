"""Đánh giá bước trả lời (gọi LLM thật) trên eval_set.jsonl.

Hành vi mong đợi:
  - câu ngoài dữ liệu (gold=null)            -> refused
  - chunk gold có lời giải / đáp án TN       -> answered
  - chunk gold chỉ có đề                     -> similar_only
Chỉ số: hành vi đúng, trích dẫn chứa chunk gold, đáp án TN đúng (nếu có), token.
Kết quả chi tiết ghi ra eval_answers_out.jsonl để soát bằng mắt.
Dùng: python eval_answers.py [--mode quick|step]
"""
import argparse
import json
import os
import re
from collections import Counter

import answer as A
from retrieve import Retriever

HERE = os.path.dirname(os.path.abspath(__file__))


def norm_tex(s):
    s = re.sub(r'\\(left|right|displaystyle|,|;|!)', '', s)
    s = s.replace(r'\dfrac', r'\frac').replace(r'\in\mathbb{Z}', '').replace(r'\mathbb{Z}', '')
    s = re.sub(r'[\s${}.,;]|k\\in|với', '', s)
    return s


def main(mode):
    items = [json.loads(l) for l in open(os.path.join(HERE, 'eval_set.jsonl'), encoding='utf-8')]
    R = Retriever()
    by_id = {d['id']: d for d in R.docs}
    from openai import OpenAI
    client = OpenAI()
    st, tok = Counter(), Counter()
    out = open(os.path.join(HERE, f'eval_answers_out_{mode}.jsonl'), 'w', encoding='utf-8')
    for it in items:
        g = by_id.get(it['gold']) if it['gold'] else None
        if g is None:
            expect = 'refused'
        elif g.get('loi_giai'):
            expect = 'answered'
        else:
            expect = 'similar_only'
        r = A.answer(it['q'], it['lop'], mode, R=R, client=client)
        tok.update(r.get('usage') or {})
        ok = r['status'] == expect
        st['n'] += 1
        st['dung_hanh_vi'] += ok
        st[f'mong_{expect}'] += 1
        st[f'mong_{expect}_dung'] += ok
        cited = [s['id'] for s in r['sources']]
        if g is not None and r['status'] != 'refused':
            st['co_nguon'] += 1
            st['trich_gold'] += it['gold'] in cited
        mcq_ok = None
        if g is not None and g.get('dap_an_tn') and r['status'] == 'answered':
            # đáp án đúng nếu nêu phương án đúng (chữ cái) hoặc nội dung của phương án đó
            L = g['dap_an_tn']
            m = re.search(rf'(?:^|\s|\|){L}\.\s*(.+?)(?=\s+[ABCD]\.|\||\n|$)', g['text'], re.S)
            opt = norm_tex(m.group(1))[:40] if m else ''
            mcq_ok = bool(re.search(rf'(phương án|đáp án|chọn)\s*\**{L}\b', r['answer'], re.I)) \
                or bool(opt and opt in norm_tex(r['answer']))
            st['tn'] += 1
            st['tn_dung'] += mcq_ok
        out.write(json.dumps({'q': it['q'], 'lop': it['lop'], 'gold': it['gold'], 'expect': expect,
                              'status': r['status'], 'reason': r.get('reason'), 'ok': ok, 'mcq_ok': mcq_ok,
                              'answer': r['answer'], 'cited': cited}, ensure_ascii=False) + '\n')
        print(f"{'✓' if ok else '✗'} mong {expect:12} | được {r['status']:12} | {it['q'][:60]}", flush=True)
    out.close()
    pct = lambda a, b: f'{st[a]}/{st[b]} = {st[a] / st[b]:.0%}' if st[b] else 'n/a'
    print('\n=== KẾT QUẢ', mode, '===')
    print('Hành vi đúng tổng      :', pct('dung_hanh_vi', 'n'))
    for e in ('answered', 'similar_only', 'refused'):
        print(f'  mong {e:13}:', pct(f'mong_{e}_dung', f'mong_{e}'))
    print('Trích dẫn chứa chunk đúng:', pct('trich_gold', 'co_nguon'))
    print('Đáp án trắc nghiệm đúng :', pct('tn_dung', 'tn'))
    print(f"Token: vào {tok['in']} ({tok['in'] / st['n']:.0f}/câu), ra {tok['out']} ({tok['out'] / st['n']:.0f}/câu)")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=['quick', 'step'], default='quick')
    main(ap.parse_args().mode)
