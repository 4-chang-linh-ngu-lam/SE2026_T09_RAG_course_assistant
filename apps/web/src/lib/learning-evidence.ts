// Confirmed learning evidence for frontend preview projections, never raw Tutor chat.
export type LearningEvidence = {
  id: string;
  studentHref?: string;
  teacherHref?: string;
  kind: 'PRACTICE' | 'ASSESSMENT' | 'ASSIGNMENT';
  classId: string;
  studentId: string;
  resourceId: string;
  title: string;
  topic: string;
  occurredAt: string;
  gradeVersion: number;
  score: number;
  maxScore: number;
};
