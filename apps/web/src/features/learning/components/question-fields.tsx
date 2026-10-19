'use client';
import type { PracticeQuestion, QuestionType } from '@/lib/domain';
export const QUESTION_LABELS: Record<QuestionType, string> = { single_choice: 'Một đáp án', multiple_choice: 'Nhiều đáp án', true_false: 'Đúng / Sai', short_answer: 'Trả lời ngắn' };
const option = (index: number) => ({ id: crypto.randomUUID(), label: String.fromCharCode(65 + index), text: '' });
export function blankQuestion(type: QuestionType, points: number, topic: string, old?: PracticeQuestion): PracticeQuestion {
  const base = { id: old?.id ?? crypto.randomUUID(), prompt: old?.prompt ?? '', explanation: old?.explanation ?? '', topic: old?.topic ?? topic, points: old?.points ?? points, sourceRef: old?.sourceRef, isReviewed: false };
  const options = old && 'options' in old ? old.options : [option(0), option(1)];
  switch (type) {
    case 'single_choice': return { ...base, type, options, correctOptionId: undefined };
    case 'multiple_choice': return { ...base, type, options, correctOptionIds: [] };
    case 'true_false': return { ...base, type, statements: [{ id: crypto.randomUUID(), label: 'a', text: '', isCorrect: undefined }, { id: crypto.randomUUID(), label: 'b', text: '', isCorrect: undefined }] };
    case 'short_answer': return { ...base, type, expectedAnswer: '', manualGradingRequired: false, isAiProposed: false };
  }
}
export function answerKeyText(q: PracticeQuestion): string {
  if (q.type === 'single_choice') return q.options.find(o => o.id === q.correctOptionId)?.text ?? 'Chưa chọn đáp án';
  if (q.type === 'multiple_choice') return q.options.filter(o => q.correctOptionIds?.includes(o.id)).map(o => o.label).join(', ') || 'Chưa chọn đáp án';
  if (q.type === 'true_false') return q.statements.map(s => `${s.label}: ${s.isCorrect === undefined ? 'chưa chọn' : s.isCorrect ? 'Đúng' : 'Sai'}`).join(' · ');
  return q.expectedAnswer || 'Chưa nhập đáp án';
}
export function QuestionFields({ question: q, index, onChange, points, types }: { question: PracticeQuestion; index: number; onChange(q: PracticeQuestion): void; points: number; types: QuestionType[] }) {
  const update = (next: PracticeQuestion) => onChange({ ...next, isReviewed: false });
  return <div className="question-fields">
    <div className="authoring-meta"><label>Loại câu hỏi<select className="input" value={q.type} onChange={e => { const type = types.find(t => t === e.target.value); if (type) update(blankQuestion(type, points, q.topic ?? '', q)); }}>{types.map(t => <option key={t} value={t}>{QUESTION_LABELS[t]}</option>)}</select></label><label>Điểm<input className="input" type="number" step="any" value={q.points ?? ''} onChange={e => update({ ...q, points: e.target.value ? Number(e.target.value) : undefined })}/></label><label>Chủ đề<input className="input" value={q.topic ?? ''} onChange={e => update({ ...q, topic: e.target.value })}/></label></div>
    <label>Nội dung câu hỏi<textarea id={`q${index + 1}-prompt`} className="input" rows={4} value={q.prompt} placeholder="Nhập nội dung câu hỏi" onChange={e => update({ ...q, prompt: e.target.value })}/></label>
    {'options' in q ? <fieldset className="answer-options"><legend>Các phương án và đáp án đúng</legend>{q.options.map((o, i) => <div className="answer-option" key={o.id}>
      <label className="answer-key"><input type={q.type === 'single_choice' ? 'radio' : 'checkbox'} name={`key-${q.id}`} aria-label={`Đáp án đúng ${o.label}`} checked={q.type === 'single_choice' ? q.correctOptionId === o.id : Boolean(q.correctOptionIds?.includes(o.id))} onChange={() => update(q.type === 'single_choice' ? { ...q, correctOptionId: o.id } : { ...q, correctOptionIds: q.correctOptionIds?.includes(o.id) ? q.correctOptionIds.filter(id => id !== o.id) : [...(q.correctOptionIds ?? []), o.id] })}/>{o.label}</label>
      <input className="input" aria-label={`Nội dung phương án ${o.label}`} value={o.text} placeholder={`Nội dung phương án ${o.label}`} onChange={e => update({ ...q, options: q.options.map((item, j) => j === i ? { ...item, text: e.target.value } : item) })}/>
      <button type="button" className="icon-button" aria-label={`Xóa phương án ${o.label}`} onClick={() => { const options = q.options.filter(item => item.id !== o.id).map((item, index) => ({ ...item, label: String.fromCharCode(65 + index) })); update(q.type === 'single_choice' ? { ...q, options, correctOptionId: q.correctOptionId === o.id ? undefined : q.correctOptionId } : { ...q, options, correctOptionIds: q.correctOptionIds?.filter(id => id !== o.id) }); }}>×</button>
    </div>)}<button className="button small" type="button" onClick={() => update({ ...q, options: [...q.options, option(q.options.length)] })}>Thêm phương án</button></fieldset> : null}
    {q.type === 'true_false' ? <fieldset className="answer-options"><legend>Các mệnh đề</legend>{q.statements.map((s, i) => <div key={s.id} className="statement-option"><input className="input" aria-label={`Mệnh đề ${s.label}`} value={s.text} placeholder="Nội dung mệnh đề" onChange={e => update({ ...q, statements: q.statements.map((item, j) => j === i ? { ...item, text: e.target.value } : item) })}/><select className="input" aria-label={`Đáp án mệnh đề ${s.label}`} value={s.isCorrect === undefined ? '' : String(s.isCorrect)} onChange={e => update({ ...q, statements: q.statements.map((item, j) => j === i ? { ...item, isCorrect: e.target.value === '' ? undefined : e.target.value === 'true' } : item) })}><option value="">Chọn đáp án</option><option value="true">Đúng</option><option value="false">Sai</option></select><button className="icon-button" type="button" aria-label={`Xóa mệnh đề ${s.label}`} onClick={() => update({ ...q, statements: q.statements.filter(item => item.id !== s.id).map((item, index) => ({ ...item, label: String.fromCharCode(97 + index) })) })}>×</button></div>)}<button className="button small" type="button" onClick={() => update({ ...q, statements: [...q.statements, { id: crypto.randomUUID(), label: String.fromCharCode(97 + q.statements.length), text: '', isCorrect: undefined }] })}>Thêm mệnh đề</button></fieldset> : null}
    {q.type === 'short_answer' ? <label>Đáp án dự kiến<input className="input" value={q.expectedAnswer ?? ''} placeholder="Nhập đáp án" onChange={e => update({ ...q, expectedAnswer: e.target.value })}/></label> : null}
    <label>Lời giải và hướng dẫn<textarea className="input" rows={3} value={q.explanation ?? ''} placeholder="Giải thích phương pháp và đáp án" onChange={e => update({ ...q, explanation: e.target.value })}/></label>
  </div>;
}
