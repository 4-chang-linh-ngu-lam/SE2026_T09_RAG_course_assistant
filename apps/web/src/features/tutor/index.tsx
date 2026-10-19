'use client';
import type { RouteDefinition } from '@/config/routes';
import type { Role, RouteParams, User, WorkspaceData } from '@/lib/domain';
import { WorkspaceFeature } from '@/features/shared/workspace-feature';
import { StudentTutorWorkspace } from './views/student-tutor-workspace';
import { TeacherTutorConfigView } from './views/teacher-tutor-config-view';

export {
  StudentTutorWorkspace,
  TeacherTutorConfigView,
};

type Props = {
  route: RouteDefinition;
  data: WorkspaceData | null;
  role: Role;
  reload(): void;
  params?: RouteParams;
  user?: User;
};

export function TutorFeature(props: Props) {
  const id = props.route.id;
  const params = props.params ?? {};

  if (id === 's.tutor') {
    return <StudentTutorWorkspace route={props.route} data={props.data} params={params} reload={props.reload} />;
  }
  if (id === 't.tutor') {
    return <TeacherTutorConfigView route={props.route} data={props.data} params={params} reload={props.reload} />;
  }

  return <WorkspaceFeature {...props} />;
}

export { TutorFeature as Feature };
