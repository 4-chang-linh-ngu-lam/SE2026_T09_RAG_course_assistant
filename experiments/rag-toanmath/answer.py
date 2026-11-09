"""Demo hỏi -> truy hồi -> LLM trả lời có trích dẫn (thử nghiệm cho TASK-018, KHÔNG phải AI Service).

Biến môi trường:
  OPENAI_API_KEY   bắt buộc (không ghi vào code/repo)
  OPENAI_MODEL     mặc định gpt-4o-mini
  RAG_MIN_SCORE    ngưỡng điểm reranker để được phép trả lời (mặc định 0.3, xem README)

Dùng: python answer.py "câu hỏi" --lop 10 [--mode step]
"""
import argparse
import json
import os
import re
import sys

from retrieve import Retriever


def _load_dotenv(path=os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')):
    """Đọc KEY=VALUE từ file .env cạnh script (không ghi đè biến môi trường đã có)."""
    if not os.path.exists(path):
        return
    for line in open(path, encoding='utf-8'):
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            v = v.strip().strip('"').strip("'")
            if v:
                os.environ.setdefault(k.strip(), v)


_load_dotenv()

MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')
MIN_SCORE = float(os.environ.get('RAG_MIN_SCORE', '0.3'))
TOP_K = 5
REFUSAL = 'Mình không tìm thấy nội dung phù hợp trong tài liệu của lớp để trả lời câu này.'

SYSTEM = """Bạn là trợ giảng Toán cho học sinh Việt Nam. Quy tắc bắt buộc:
1. CHỈ dùng thông tin trong các NGUỒN được cung cấp. Không dùng kiến thức ngoài nguồn.
2. Mỗi ý lấy từ nguồn phải ghi trích dẫn dạng [số], ví dụ [1] hoặc [2][3]. Chỉ dùng số nguồn có trong danh sách.
3. Nếu các nguồn không đủ để trả lời, trả về đúng một dòng: KHONG_DU_CAN_CU
4. Viết công thức bằng LaTeX trong $...$. Trả lời bằng tiếng Việt, ngắn gọn, rõ ràng.
5. Nguồn là đề thi; nếu nguồn chỉ có đề mà không có lời giải, nói rõ đây là bài tương tự trong đề,
   không tự bịa đáp án và không khẳng định đáp án đúng của đề."""

MODE_HINT = {
    'quick': 'Chế độ HỎI NHANH: trả lời trực tiếp, tối đa 5 câu.',
    'step': 'Chế độ TỪNG BƯỚC: gợi ý cách làm theo từng bước đánh số, không giải hộ toàn bộ ngay; '
            'chỉ dùng các bước có căn cứ trong nguồn.',
}


def source_label(d):
    loc = ' '.join(x for x in [f"Phần {d['phan']}" if d['phan'] else '', f"Câu {d['cau']}"] if x)
    return f"Lớp {d['lop']} · {d['loai_de']} {d['nam_hoc'] or ''} · {d['truong'] or d['bo_de']} · {d['file']} · {loc}"


def build_prompt(q, docs, mode):
    parts = []
    for i, d in enumerate(docs, 1):
        body = d['text'] + (('\n[Lời giải]\n' + d['loi_giai']) if d.get('loi_giai') else '')
        parts.append(f'NGUỒN [{i}] ({source_label(d)}):\n{body[:2500]}')
    return MODE_HINT[mode] + '\n\n' + '\n\n'.join(parts) + f'\n\nCÂU HỎI CỦA HỌC SINH: {q}'


def check_citations(text, n):
    """Fail closed: phải có ít nhất 1 trích dẫn, và mọi trích dẫn phải trỏ tới nguồn có thật."""
    cited = [int(x) for x in re.findall(r'\[(\d+)\]', text)]
    if not cited:
        return False, 'không có trích dẫn'
    bad = [c for c in cited if not 1 <= c <= n]
    if bad:
        return False, f'trích dẫn nguồn không tồn tại: {bad}'
    return True, sorted(set(cited))


def answer(q, lop, mode='quick', R=None, client=None):
    R = R or Retriever()
    docs = R.search(q, lop, top=TOP_K, mode='rerank')
    if not docs or docs[0]['score'] < MIN_SCORE:
        return {'status': 'refused', 'reason': 'điểm truy hồi thấp', 'answer': REFUSAL, 'sources': []}
    if client is None:
        from openai import OpenAI
        client = OpenAI()  # đọc OPENAI_API_KEY từ môi trường
    r = client.chat.completions.create(
        model=MODEL, temperature=0.2,
        messages=[{'role': 'system', 'content': SYSTEM},
                  {'role': 'user', 'content': build_prompt(q, docs, mode)}])
    text = r.choices[0].message.content.strip()
    usage = {'in': r.usage.prompt_tokens, 'out': r.usage.completion_tokens}
    if 'KHONG_DU_CAN_CU' in text:
        return {'status': 'refused', 'reason': 'LLM: không đủ căn cứ', 'answer': REFUSAL, 'sources': [], 'usage': usage}
    ok, info = check_citations(text, len(docs))
    if not ok:
        return {'status': 'refused', 'reason': f'kiểm tra trích dẫn thất bại ({info})', 'answer': REFUSAL,
                'sources': [], 'usage': usage}
    return {'status': 'answered', 'answer': text, 'usage': usage,
            'sources': [{'n': i, 'id': docs[i - 1]['id'], 'label': source_label(docs[i - 1])} for i in info]}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('q')
    ap.add_argument('--lop', type=int, required=True)
    ap.add_argument('--mode', choices=['quick', 'step'], default='quick')
    a = ap.parse_args()
    if not os.environ.get('OPENAI_API_KEY'):
        sys.exit('Thiếu OPENAI_API_KEY trong biến môi trường.')
    res = answer(a.q, a.lop, a.mode)
    print(res['answer'])
    for s in res['sources']:
        print(f"  [{s['n']}] {s['label']}")
    print(json.dumps({k: res[k] for k in ('status', 'reason', 'usage') if k in res}, ensure_ascii=False))
