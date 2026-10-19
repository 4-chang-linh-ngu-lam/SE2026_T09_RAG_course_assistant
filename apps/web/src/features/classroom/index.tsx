'use client';
import type { RouteDefinition } from '@/config/routes';
import type { Role, RouteParams, User, WorkspaceData } from '@/lib/domain';
import { WorkspaceFeature } from '@/features/shared/workspace-feature';
import { StudentHomeFeature } from './student-home';
import { StudentClassesFeature } from './student-classes';
import { ClassOverviewFeature } from './class-overview';
import { StudentHistoryFeature } from './student-history';
import { TeacherHomeFeature } from './teacher-home';
import { TeacherClassesFeature } from './teacher-classes';
import { TeacherOverviewFeature } from './teacher-overview';

export {
  StudentHomeFeature,
  StudentClassesFeature,
  ClassOverviewFeature,
  StudentHistoryFeature,
  TeacherHomeFeature,
  TeacherClassesFeature,
  TeacherOverviewFeature,
};

type Props = {
  route: RouteDefinition;
  data: WorkspaceData | null;
  role: Role;
  reload(): void;
  params?: RouteParams;
  user?: User;
};

export function ClassroomFeature(props: Props) {
  const id = props.route.id;
  if (id === 's.home') return <StudentHomeFeature route={props.route} data={props.data} reload={props.reload} />;
  if (id === 's.classes') return <StudentClassesFeature route={props.route} data={props.data} reload={props.reload} />;
  if (id === 's.overview') return <ClassOverviewFeature route={props.route} data={props.data} reload={props.reload} />;
  if (id === 's.history') return <StudentHistoryFeature route={props.route} data={props.data} reload={props.reload} />;
  if (id === 't.home') return <TeacherHomeFeature route={props.route} data={props.data} reload={props.reload} />;
  if (id === 't.classes') return <TeacherClassesFeature route={props.route} data={props.data} reload={props.reload} />;
  if (id === 't.overview') return <TeacherOverviewFeature route={props.route} data={props.data} reload={props.reload} />;
  return <WorkspaceFeature {...props} />;
}

export { ClassroomFeature as Feature };
