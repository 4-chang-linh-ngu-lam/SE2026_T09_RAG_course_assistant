'use client';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import {useGuardedRouter as useRouter} from '@/components/unsaved-changes';
import type { RouteDefinition } from '@/config/routes';
import type { PracticeQuestion, QuestionType, Role, RouteParams, User, WorkspaceData } from '@/lib/domain';
import type { PracticeAiProposal, PracticeDraftContent, PracticeEditorSnapshot } from '@/lib/practice-authoring';
import { adapter } from '@/lib/data';
import { ApiError, errorMessage } from '@/lib/api/errors';
import { draftStore } from '@/lib/draft-store';
import { Dialog, ErrorNotice, StatePanel, useUnsavedChanges } from '@/components/ui';
import { ClassSourcePreviewDialog, type SourcePreviewRequest } from '@/features/document/class-source-preview';
import { QuestionRenderer } from '../components/question-renderer';
import { answerKeyText, blankQuestion, QuestionFields, QUESTION_LABELS } from '../components/question-fields';
import './practice-authoring.css';

type Props = { route: RouteDefinition; data: WorkspaceData | null; role: Role; reload(): void; params: RouteParams; user: User };
type Cached = { revision: string; content: PracticeDraftContent; selectedId: string };
const contentOf = (snapshot: PracticeEditorSnapshot): PracticeDraftContent => ({ title: snapshot.editor.title, topic: snapshot.editor.topic, questions: structuredClone(snapshot.editor.questions) });
const sameContent = (a: PracticeDraftContent, b: PracticeDraftContent) => JSON.stringify(a) === JSON.stringify(b);

export function TeacherPracticeEditorView({ params, user }: Props) {
  const router = useRouter();
  const scope = { classId: params.classId ?? '', practiceId: params.practiceId ?? '' };
  const identity = JSON.stringify([user.id, scope.classId, scope.practiceId]);
  const generation = useRef(0);
  const [snapshot, setSnapshot] = useState<PracticeEditorSnapshot | null>(null);
  const [content, setContent] = useState<PracticeDraftContent | null>(null);
  const [selectedId, setSelectedId] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [preview, setPreview] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [publishOpen, setPublishOpen] = useState(false);
  const [removeOpen, setRemoveOpen] = useState(false);
  const [replaceOpen, setReplaceOpen] = useState(false);
  const [remote, setRemote] = useState<PracticeEditorSnapshot | null>(null);
  const [sourceId, setSourceId] = useState('');
  const [proposalType, setProposalType] = useState<QuestionType>('short_answer');
  const [proposal, setProposal] = useState<PracticeAiProposal | null>(null);
  const [sourcePreview, setSourcePreview] = useState<SourcePreviewRequest | null>(null);
  const draftKey = `${user.id}:practice-editor:${scope.classId}:${scope.practiceId}`;
  const dirty = Boolean(snapshot && content && !sameContent(content, contentOf(snapshot)));
  useUnsavedChanges(dirty);

  useEffect(() => {
    const token = ++generation.current;
    setSnapshot(null); setContent(null); setError(null);
    void adapter.practiceAuthoring.load(scope).then(value => {
      if (generation.current !== token) return;
      const cached = draftStore.get<Cached>(draftKey);
      setSnapshot(value);
      setContent(cached?.content ?? contentOf(value));
      setSelectedId(cached?.selectedId ?? value.editor.questions[0]?.id ?? '');
      if (cached && cached.revision !== value.revision) { setBlocked(true); setError('Bản nháp trên máy chủ đã thay đổi. Bản đang soạn vẫn được giữ trong phiên; hãy đối chiếu trước khi lưu.'); }
    }).catch(err => { if (generation.current === token) setError(errorMessage(err)); });
    return () => { ++generation.current; };
  }, [identity]);

  useEffect(() => {
    if (!snapshot || !content) return;
    if (!dirty) { draftStore.remove(draftKey); return; }
    draftStore.set<Cached>(draftKey, { revision: snapshot.revision, content: structuredClone(content), selectedId });
  }, [snapshot, content, selectedId, draftKey, dirty]);

  const adopt = (value: PracticeEditorSnapshot) => {
    setSnapshot(value); setContent(contentOf(value)); setBlocked(false);
    setSelectedId(old => value.editor.questions.some(q => q.id === old) ? old : value.editor.questions[0]?.id ?? '');
  };
  async function action(run: () => Promise<void>) {
    if (busy) return;
    const token = generation.current;
    setBusy(true); setError(null); setNotice('');
    try { await run(); } catch (err) {
      if (generation.current !== token) return;
      setError(errorMessage(err));
      if (err instanceof ApiError && (err.outcome === 'unknown' || err.status === 409)) setBlocked(true);
      if (err instanceof ApiError && [401, 403, 404].includes(err.status)) { draftStore.remove(draftKey); setSnapshot(null); setContent(null); }
    } finally { if (generation.current === token) setBusy(false); }
  }
  async function saveCurrent(): Promise<PracticeEditorSnapshot> {
    if (!snapshot || !content || blocked) throw new Error('Đối chiếu bản nháp trước khi lưu.');
    if (!dirty) return snapshot;
    const token = generation.current;
    const saved = await adapter.practiceAuthoring.save({ ...scope, expectedRevision: snapshot.revision, content: structuredClone(content) });
    if (generation.current !== token) throw new Error('Trang soạn thảo đã thay đổi.');
    adopt(saved);
    return saved;
  }
  function updateQuestion(updated: PracticeQuestion) {
    setContent(old => old ? { ...old, questions: old.questions.map(q => q.id === updated.id ? { ...updated, isReviewed: false } : q) } : old);
    setProposal(null); setNotice('');
  }
  function moveQuestion(direction: number) {
    if (!content) return;
    const index = content.questions.findIndex(q => q.id === selectedId);
    if (index + direction < 0 || index + direction >= content.questions.length) return;
    const questions = [...content.questions];
    [questions[index], questions[index + direction]] = [questions[index + direction], questions[index]];
    setContent({ ...content, questions });
  }
  const selectedIndex = content?.questions.findIndex(q => q.id === selectedId) ?? -1;
  const question = content?.questions[selectedIndex];
  const reviewed = content?.questions.filter(q => q.isReviewed).length ?? 0;
  const canPublish = Boolean(snapshot?.editor.isDraft && snapshot.editor.canPublish && content?.questions.length && !dirty && !blocked);
  const selectedSource = snapshot?.editor.availableClassSources.find(s => s.id === sourceId);
  const openSource = (documentId: string, version: number, page?: number) => setSourcePreview({ classId: scope.classId, documentId, version, page });
  if (!snapshot || !content) return <StatePanel busy={!error} title={error ? 'Chưa thể mở bản soạn thảo' : 'Đang mở bản soạn thảo…'} message={error ?? undefined}><Link href={`/teacher/classes/${scope.classId}/activities`} className="button">Về hoạt động học tập</Link></StatePanel>;

  return <div className="practice-editor-workspace">
    <div className="authoring-toolbar card"><div><Link href={`/teacher/classes/${scope.classId}/activities`}>← Quay lại</Link><p className="muted">{snapshot.editor.className} · {snapshot.editor.versionLabel}</p><h1>{content.title || 'Bản nháp chưa đặt tên'}</h1><p>{reviewed}/{content.questions.length} câu đã duyệt · {dirty ? 'Có thay đổi chưa lưu' : 'Đã đồng bộ bản nháp'}</p></div><div className="actions"><button id="ux-practice-save" className="button" disabled={busy || blocked || !dirty} onClick={() => void action(async () => { await saveCurrent(); setNotice('Đã lưu đúng nội dung bản nháp.'); })}>Lưu bản nháp</button><button id="ux-practice-preview" className="button" disabled={busy || !content.questions.length} onClick={() => setPreview(true)}>Xem trước</button><button className="button" disabled={busy} onClick={() => setReviewOpen(true)}>Rà soát bài luyện tập</button><button id="ux-practice-publish" className="button primary" disabled={busy || !canPublish} onClick={() => setPublishOpen(true)}>Công bố bài luyện tập</button></div></div>
    <ErrorNotice message={error}/>{notice && <p className="notice" role="status">{notice}</p>}
    {blocked && <button className="button" disabled={busy} onClick={() => void action(async () => { const token = generation.current; const value = await adapter.practiceAuthoring.load(scope); if (token !== generation.current) return; setRemote(value); setReplaceOpen(true); })}>Đối chiếu với bản trên máy chủ</button>}
    <fieldset disabled={busy} className="authoring-content"><legend className="sr-only">Nội dung bản nháp</legend>
      <div className="authoring-meta card"><label>Tên bài luyện tập<input className="input" value={content.title} onChange={e => setContent({ ...content, title: e.target.value })}/></label><label>Chủ đề kiến thức<input className="input" value={content.topic} onChange={e => setContent({ ...content, topic: e.target.value })}/></label></div>
      <div className="practice-editor-grid">
        <aside className="card question-palette"><h2>Danh sách câu hỏi <span className="muted">{content.questions.length}</span></h2>{content.questions.map((q, i) => <button key={q.id} type="button" data-question-id={q.id} aria-pressed={q.id === selectedId} onClick={() => setSelectedId(q.id)}><strong>{i + 1}. {QUESTION_LABELS[q.type]}</strong><span>{q.prompt || 'Chưa có nội dung'}</span><small>{q.isReviewed ? 'Đã duyệt' : 'Cần duyệt'}</small></button>)}<button className="button" type="button" onClick={() => { const q = blankQuestion('single_choice', snapshot.defaultPoints, content.topic); setContent({ ...content, questions: [...content.questions, q] }); setSelectedId(q.id); }}>+ Thêm câu hỏi</button><p className="muted">Bản nháp mới không thay đổi nội dung học sinh đang làm.</p></aside>
        <section className="card question-edit-panel">{question ? <><div className="section-heading"><h2>Câu hỏi {selectedIndex + 1}</h2><span className={`badge ${question.isReviewed ? 'success' : 'warning'}`}>{question.isReviewed ? 'Đã duyệt nháp' : 'Cần duyệt'}</span></div><QuestionFields question={question} index={selectedIndex} onChange={updateQuestion} points={snapshot.defaultPoints} types={snapshot.questionTypes}/>{question.sourceRef && <button className="button small" type="button" onClick={() => openSource(question.sourceRef!.documentId, question.sourceRef!.versionNumber, question.sourceRef!.pageNumber)}>Đọc nguồn: {question.sourceRef.displayText || question.sourceRef.documentTitle}</button>}<div className="actions"><button className="button" type="button" disabled={selectedIndex === 0} onClick={() => moveQuestion(-1)}>↑ Lên trên</button><button className="button" type="button" disabled={selectedIndex === content.questions.length - 1} onClick={() => moveQuestion(1)}>↓ Xuống dưới</button><button className="button danger" type="button" onClick={() => setRemoveOpen(true)}>Xóa câu hỏi</button></div><button className="button primary" type="button" data-action="review-question" disabled={blocked || !question.prompt.trim()} onClick={() => void action(async () => { const id = question.id; const saved = await saveCurrent(); const token = generation.current; const reviewedSnapshot = await adapter.practiceAuthoring.review({ ...scope, expectedRevision: saved.revision, questionId: id, approved: !question.isReviewed || dirty }); if (generation.current !== token) return; adopt(reviewedSnapshot); setNotice('Trạng thái duyệt đã được xác nhận cho nội dung vừa lưu.'); })}>{question.isReviewed && !dirty ? 'Bỏ duyệt câu hỏi' : 'Duyệt câu hỏi này'}</button></> : <StatePanel title="Chưa có câu hỏi" message="Thêm câu hỏi để bắt đầu soạn bài."/>}</section>
        <aside className="card authoring-ai"><h2>✧ Trợ lý Lumi</h2><label>Nguồn tài liệu của lớp<select className="input" value={sourceId} onChange={e => { setSourceId(e.target.value); setProposal(null); }}><option value="">Chọn nguồn đã sẵn sàng</option>{snapshot.editor.availableClassSources.map(s => <option key={`${s.id}:${s.version}`} value={s.id} disabled={!s.isReady}>{s.title} · v{s.version}{s.isReady ? '' : ' · Chưa sẵn sàng'}</option>)}</select></label>{selectedSource && <button className="button small" type="button" onClick={() => openSource(selectedSource.id, selectedSource.version)}>Đọc nguồn đã chọn</button>}<label>Loại câu hỏi gợi ý<select className="input" value={proposalType} onChange={e => { const type = snapshot.questionTypes.find(t => t === e.target.value); if (type) setProposalType(type); }}>{snapshot.questionTypes.map(type => <option key={type} value={type}>{QUESTION_LABELS[type]}</option>)}</select></label><button className="button ai" type="button" disabled={!selectedSource?.isReady || blocked} onClick={() => void action(async () => { const saved = await saveCurrent(); const token = generation.current; const value = await adapter.practiceAuthoring.propose({ ...scope, expectedRevision: saved.revision, sourceId: selectedSource!.id, sourceVersion: selectedSource!.version, type: proposalType }); if (generation.current === token) setProposal(value); })}>Đề xuất câu hỏi</button>{proposal && <div className="proposal-card"><span className="badge warning">Chờ giáo viên rà soát</span><p>{proposal.question.prompt}</p><p><strong>Đáp án dự kiến:</strong> {answerKeyText(proposal.question)}</p><p>{proposal.question.explanation}</p><div className="actions"><button className="button" type="button" onClick={() => { setContent({ ...content, questions: [...content.questions, { ...proposal.question, isReviewed: false }] }); setSelectedId(proposal.question.id); setProposal(null); }}>Thêm vào bản nháp và sửa</button><button className="button" type="button" onClick={() => setProposal(null)}>Loại gợi ý</button></div><p className="muted">Sau khi thêm, giáo viên duyệt câu hỏi trong bản nháp trước khi công bố.</p></div>}</aside>
      </div>
    </fieldset>
    <Dialog open={preview} title="Xem trước bài luyện tập" onClose={() => setPreview(false)} className="practice-preview"><p>Nội dung hiện đang soạn · {dirty ? 'Có thay đổi chưa lưu' : snapshot.editor.versionLabel}</p><div className="practice-preview-scroll">{content.questions.map((q, i) => <QuestionRenderer key={q.id} question={{ ...q, sourceRef: undefined, sourceReference: undefined }} questionNumber={i + 1} readOnly/>)}</div></Dialog>
    <Dialog open={reviewOpen} title="Rà soát trước khi công bố" onClose={() => setReviewOpen(false)}><p>{reviewed}/{content.questions.length} câu đã duyệt. {dirty ? 'Lưu và duyệt các thay đổi trước khi công bố.' : ''}</p>{content.questions.map((q, i) => <button className="button review-row" key={q.id} onClick={() => { setSelectedId(q.id); setReviewOpen(false); }}>Câu {i + 1}: {q.isReviewed ? 'Đã duyệt' : 'Cần duyệt'} · {q.prompt || 'Chưa có nội dung'}</button>)}<button className="button primary" disabled={!canPublish} onClick={() => { setReviewOpen(false); setPublishOpen(true); }}>Tiếp tục công bố</button></Dialog>
    <Dialog open={publishOpen} title="Công bố bài luyện tập?" busy={busy} onClose={() => setPublishOpen(false)}><p>Công bố phiên bản {snapshot.editor.currentVersionNumber} với đúng {content.questions.length} câu đã duyệt. Các lượt học sinh đang làm giữ nguyên phiên bản đã bắt đầu.</p><ErrorNotice message={error}/><div className="actions"><button className="button" disabled={busy} onClick={() => setPublishOpen(false)}>Quay lại</button><button className="button primary" disabled={busy || !canPublish} onClick={() => void action(async () => { const token = generation.current; await adapter.practiceAuthoring.publish({ ...scope, expectedRevision: snapshot.revision }); if (generation.current !== token) return; draftStore.remove(draftKey); setPublishOpen(false); router.pushConfirmed(`/teacher/classes/${scope.classId}/activities`); })}>Xác nhận công bố</button></div></Dialog>
    <Dialog open={removeOpen} title="Xóa câu hỏi khỏi bản nháp?" onClose={() => setRemoveOpen(false)}><p>Câu hỏi chỉ được xóa khỏi bản đang soạn.</p><button className="button danger" onClick={() => { const next = content.questions.filter(q => q.id !== selectedId); setContent({ ...content, questions: next }); setSelectedId(next[Math.min(selectedIndex, next.length - 1)]?.id ?? ''); setRemoveOpen(false); }}>Xóa câu hỏi</button></Dialog>
    <Dialog open={replaceOpen} title="Đối chiếu bản nháp" onClose={() => setReplaceOpen(false)}><p>Bản đang soạn vẫn được giữ. Chỉ thay bằng nội dung trên máy chủ khi bạn đã đối chiếu xong.</p>{remote && <div className="card"><strong>{remote.editor.title}</strong><p>{remote.editor.questions.length} câu · {remote.editor.reviewedCount} đã duyệt</p></div>}<div className="actions"><button className="button" onClick={() => setReplaceOpen(false)}>Giữ bản đang soạn</button><button className="button primary" onClick={() => { if (remote) adopt(remote); setReplaceOpen(false); setError(null); }}>Dùng bản trên máy chủ</button></div></Dialog>
    <ClassSourcePreviewDialog request={sourcePreview} onClose={() => setSourcePreview(null)}/>
  </div>;
}
