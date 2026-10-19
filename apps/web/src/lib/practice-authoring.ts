import type { PracticeQuestion, QuestionType, TeacherPracticeEditorModel } from './domain';

// Frontend authoring contract; does not describe an unapproved HTTP API.
export type PracticeDraftContent = Pick<TeacherPracticeEditorModel, 'title' | 'topic' | 'questions'>;
export type PracticeEditorSnapshot = {
  editor: TeacherPracticeEditorModel;
  revision: string;
  defaultPoints: number;
  questionTypes: QuestionType[];
};
export type PracticeAuthoringScope = { classId: string; practiceId: string };
export type PracticeAiProposal = { id: string; question: PracticeQuestion; sourceId: string; sourceVersion: number };
export interface PracticeAuthoringPort {
  load(scope: PracticeAuthoringScope): Promise<PracticeEditorSnapshot>;
  save(input: PracticeAuthoringScope & { expectedRevision: string; content: PracticeDraftContent }): Promise<PracticeEditorSnapshot>;
  review(input: PracticeAuthoringScope & { expectedRevision: string; questionId: string; approved: boolean }): Promise<PracticeEditorSnapshot>;
  publish(input: PracticeAuthoringScope & { expectedRevision: string }): Promise<{ publishedVersionId: string }>;
  propose(input: PracticeAuthoringScope & { expectedRevision: string; sourceId: string; sourceVersion: number; type: QuestionType }): Promise<PracticeAiProposal>;
}
