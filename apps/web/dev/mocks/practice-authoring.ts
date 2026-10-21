import { ApiError } from '../../src/lib/api/errors';
import type { DataAdapter } from '../../src/lib/data/port';
import type { PracticeQuestion, TeacherPracticeEditorModel } from '../../src/lib/domain';
import type { PracticeAuthoringPort, PracticeAuthoringScope, PracticeEditorSnapshot } from '../../src/lib/practice-authoring';
import type { PreviewContext } from './context';
import { initialTeacherPracticeEditors } from './fixtures';

type Dependencies = { context: PreviewContext; learning(): DataAdapter['learning']; read(scope: PracticeAuthoringScope): Promise<TeacherPracticeEditorModel> };
function revision(editor: TeacherPracticeEditorModel): string {
  // Exact opaque snapshot equality, kept in memory; no hash collisions or wire headers.
  return JSON.stringify([editor.classId, editor.practiceId, editor.currentVersionNumber, editor.isDraft, editor.title, editor.topic, editor.questions]);
}
export function createPracticeAuthoringPort(deps: Dependencies): PracticeAuthoringPort {
  function authorize(scope: PracticeAuthoringScope) {
    const actor = deps.context.actor();
    if (!actor.roles.includes('LECTURER') || !deps.context.teachingRole(actor.id, scope.classId) || deps.context.classSummary(scope.classId)?.status !== 'ACTIVE') {
      throw new ApiError('FORBIDDEN', 'Bạn không được soạn bài trong lớp này.', 403);
    }
    return actor;
  }
  function assertActor(scope: PracticeAuthoringScope, actorId: string, mutated = false) {
    if (authorize(scope).id !== actorId) throw new ApiError('SESSION_CHANGED', 'Phiên đăng nhập đã thay đổi. Hãy mở lại bài trong phiên hiện tại.', 401, mutated ? 'unknown' : 'rejected');
  }
  async function load(scope: PracticeAuthoringScope, signal?: AbortSignal): Promise<PracticeEditorSnapshot> {
    signal?.throwIfAborted();
    const actorId = authorize(scope).id;
    const editor = await deps.read(scope);
    signal?.throwIfAborted();
    assertActor(scope, actorId);
    if (editor.classId !== scope.classId || editor.practiceId !== scope.practiceId) throw new ApiError('NOT_FOUND', 'Không tìm thấy bài luyện tập.', 404);
    return { editor, classSummary: structuredClone(deps.context.classSummary(scope.classId)), revision: revision(editor), defaultPoints: 1, questionTypes: ['single_choice', 'multiple_choice', 'true_false', 'short_answer'] };
  }
  async function match(scope: PracticeAuthoringScope, expected: string) {
    const current = await load(scope);
    if (current.revision !== expected) throw new ApiError('CONFLICT', 'Bản nháp đã thay đổi. Hãy tải lại và đối chiếu trước khi tiếp tục.', 409);
    return current;
  }
  return {
    load,
    async save(input) {
      const actorId = authorize(input).id;
      const current = await match(input, input.expectedRevision);
      if (!input.content.title.trim() || !input.content.topic.trim()) throw new ApiError('VALIDATION_ERROR', 'Nhập tên bài và chủ đề kiến thức.', 422);
      const content = structuredClone(input.content);
      if (new Set(content.questions.map(q => q.id)).size !== content.questions.length) throw new ApiError('VALIDATION_ERROR', 'Mã câu hỏi bị trùng.', 422);
      const sameContent = current.editor.title === content.title && current.editor.topic === content.topic && JSON.stringify(current.editor.questions) === JSON.stringify(content.questions);
      assertActor(input, actorId);
      if (!sameContent) await deps.learning().savePracticeEditorDraft({ ...input, ...content });
      assertActor(input, actorId, !sameContent);
      const result = await load(input);
      const unreviewed = (questions: PracticeQuestion[]) => questions.map(({ isReviewed: _reviewed, ...q }) => q);
      if (result.editor.title !== content.title || result.editor.topic !== content.topic || JSON.stringify(unreviewed(result.editor.questions)) !== JSON.stringify(unreviewed(content.questions))) {
        throw new ApiError('CONFLICT', 'Nội dung đã thay đổi trong lúc lưu. Hãy đối chiếu bản nháp mới.', 409);
      }
      return result;
    },
    async review(input) {
      const actorId = authorize(input).id;
      await match(input, input.expectedRevision);
      assertActor(input, actorId);
      await deps.learning().reviewEditorQuestion(input);
      assertActor(input, actorId, true);
      return load(input);
    },
    async publish(input) {
      const actorId = authorize(input).id;
      const current = await match(input, input.expectedRevision);
      if (!current.editor.canPublish || !current.editor.questions.length || current.editor.questions.some(q => !q.isReviewed)) throw new ApiError('VALIDATION_ERROR', 'Duyệt đủ câu hỏi của bản nháp hiện tại trước khi công bố.', 422);
      assertActor(input, actorId);
      const result = await deps.learning().publishPractice(input);
      assertActor(input, actorId, true);
      return { publishedVersionId: result.publishedVersionId };
    },
    async propose(input) {
      const actor = authorize(input);
      await match(input, input.expectedRevision);
      assertActor(input, actor.id);
      const source = deps.context.sources(input.classId).find(s => s.id === input.sourceId && s.version === input.sourceVersion && s.isReady);
      if (!source || !deps.context.sourceAccessible(actor.id, input.classId, source.id, source.version)) throw new ApiError('FORBIDDEN', 'Nguồn tài liệu này chưa sẵn sàng hoặc không còn được chia sẻ.', 403);
      // Curated preview candidates are held only in this development module.
      const authored = Object.values(initialTeacherPracticeEditors).filter(e => e.classId === input.classId).flatMap(e => e.questions);
      const template = authored.find(q => q.type === input.type && q.sourceRef?.documentId === source.id && q.sourceRef.versionNumber === source.version);
      if (!template) throw new ApiError('UNAVAILABLE', 'Chưa có gợi ý phù hợp với nguồn và loại câu hỏi này. Bạn có thể tự soạn câu hỏi.', 503);
      const id = crypto.randomUUID();
      const question = { ...structuredClone(template), id: crypto.randomUUID(), isReviewed: false };
      return { id, question, sourceId: source.id, sourceVersion: source.version };
    },
  };
}
