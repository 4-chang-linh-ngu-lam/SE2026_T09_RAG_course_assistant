'use client';
import type { RouteDefinition } from '@/config/routes';
import type { Role, RouteParams, User, WorkspaceData } from '@/lib/domain';
import { WorkspaceFeature } from '@/features/shared/workspace-feature';
import { StudentPracticeListView } from './views/student-practice-list-view';
import { StudentPracticeAttemptView } from './views/student-practice-attempt-view';
import { StudentPracticeResultView } from './views/student-practice-result-view';
import { TeacherActivitiesView } from './views/teacher-activities-view';
import { TeacherPracticeEditorView } from './views/teacher-practice-editor-view';

type Props = {
  route: RouteDefinition;
  data: WorkspaceData | null;
  role: Role;
  reload(): void;
  params: RouteParams;
  user: User;
};

export function LearningFeature(props: Props) {
  const { route } = props;

  if (route.id === 's.practice') {
    return <StudentPracticeListView {...props} />;
  }

  if (route.id === 's.practiceAttempt') {
    return <StudentPracticeAttemptView {...props} />;
  }

  if (route.id === 's.practiceResult') {
    return <StudentPracticeResultView {...props} />;
  }

  if (route.id === 't.activities') {
    return <TeacherActivitiesView {...props} />;
  }

  if (route.id === 't.practiceEditor') {
    return <TeacherPracticeEditorView {...props} />;
  }

  return <WorkspaceFeature {...props} />;
}

export { LearningFeature as Feature };
