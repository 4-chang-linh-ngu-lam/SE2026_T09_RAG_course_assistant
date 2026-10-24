'use client';
import dynamic from 'next/dynamic';
import type { RouteDefinition } from '@/config/routes';
import type { Role, RouteParams, User, WorkspaceData } from '@/lib/domain';
import { ProfileFeature } from './identity/profile';
import { MyDataRequestsFeature } from './identity/data-requests';
import { ProvisioningFeature } from './identity/provisioning';
import { NotificationFeature } from './notification';
import { CalendarFeature, ClassFeedFeature } from './social';
import {
  StudentHomeFeature,
  StudentClassesFeature,
  ClassOverviewFeature,
  StudentHistoryFeature,
  TeacherHomeFeature,
  TeacherClassesFeature,
  TeacherOverviewFeature,
} from './classroom';
import { Feature as Classroom } from './classroom';
import { Feature as Social } from './social';
import { Feature as Notification } from './notification';
import { Feature as Administration } from './administration';
import {adapter} from '@/lib/data';
import {usesCoreAdminUi} from '@/lib/core-admin-routing';
import {coreManagementRoutes,type CoreManagementRoute} from '@/lib/core-management-controller';
const CoreAdmin=dynamic(()=>import('./administration/core-admin-feature').then(m=>m.CoreAdminFeature));
const CoreManagement=dynamic(()=>import('./administration/core-management-feature').then(m=>m.CoreManagementFeature));
const Document = dynamic(() => import('./document').then(m => m.Feature));
const Tutor = dynamic(() => import('./tutor').then(m => m.Feature));
const Learning = dynamic(() => import('./learning').then(m => m.Feature));
const Intelligence = dynamic(() => import('./intelligence').then(m => m.IntelligenceFeature));
const intelligenceRoutes = new Set(['s.progress','t.analytics','t.studentAnalytics','a.dataRequests','a.audit','a.reports','a.exports']);

type Props = {
  route: RouteDefinition;
  data: WorkspaceData | null;
  role: Role;
  reload(): void;
  params: RouteParams;
  user: User;
};

const Assessment = dynamic(() => import('./assessment').then(m => m.AssessmentFeature));
const Assignment = dynamic(() => import('./assignment').then(m => m.AssignmentFeature));
const ClassroomAdmin = dynamic(() => import('./classroom-admin').then(m => m.ClassroomAdminFeature));
const classroomAdminRoutes = new Set(['a.catalog','a.homerooms','a.homeroom','a.classes','a.newClass','a.classSettings','a.enrollment','a.lifecycle']);
const Accounts = dynamic(() => import('./accounts').then(m => m.AccountsFeature));
const assessmentRoutes = new Set(['s.assessments','s.assessment','s.examAttempt','s.receipt','s.examResult','t.assessmentEditor','t.assessmentApproval','t.examGrading']);
const assignmentRoutes = new Set(['s.assignments','s.assignment','s.historyResult','t.assignmentEditor','t.gradingQueue','t.assignmentGrading','t.correction','t.correctionApproval']);
const accountRoutes = new Set(['a.accounts','a.account','a.legacy','a.staffInvite','a.importNew','a.import']);

export function FeatureEntry(props: Props) {
  const id = props.route.id;
  if(adapter.source==='live'&&id==='s.home')return <StudentClassesFeature route={props.route} data={props.data} reload={props.reload}/>;
  if(adapter.source==='live'&&id==='t.home')return <TeacherClassesFeature route={props.route} data={props.data} reload={props.reload}/>;
  if(adapter.source==='live'&&(coreManagementRoutes as readonly string[]).includes(id))return <CoreManagement routeId={id as CoreManagementRoute} params={props.params}/>;
  if(usesCoreAdminUi(adapter.source,id))return <CoreAdmin key={JSON.stringify([id,props.user.id,props.user.school_id,props.user.roles])} routeId={id}/>;

  // Identity owned routes
  if (id === 'account.profile') return <ProfileFeature />;
  if (id === 'account.requests') return <MyDataRequestsFeature />;
  if (id === 'a.newStudent') return <ProvisioningFeature />;

  // Notification owned route
  if (id === 'account.notifications') {
    return (
      <NotificationFeature
        data={props.data}
        role={props.role}
        params={props.params}
        reload={props.reload}
        route={props.route}
        user={props.user}
      />
    );
  }

  // Social & Calendar owned routes
  if (id === 'account.calendar') {
    return (
      <CalendarFeature
        data={props.data}
        role={props.role}
        params={props.params}
        reload={props.reload}
        isGlobal
      />
    );
  }
  if (id === 's.calendar' || id === 't.calendar') {
    return (
      <CalendarFeature
        data={props.data}
        role={props.role}
        params={props.params}
        reload={props.reload}
        isGlobal={false}
      />
    );
  }
  if (id === 's.feed' || id === 't.feed') {
    return (
      <ClassFeedFeature
        data={props.data}
        role={props.role}
        user={props.user}
        params={props.params}
        reload={props.reload}
      />
    );
  }

  // Classroom owned routes
  if (id === 's.home') {
    return <StudentHomeFeature route={props.route} data={props.data} reload={props.reload} />;
  }
  if (id === 's.classes') {
    return <StudentClassesFeature route={props.route} data={props.data} reload={props.reload} />;
  }
  if (id === 's.overview') {
    return <ClassOverviewFeature route={props.route} data={props.data} reload={props.reload} />;
  }
  if (id === 's.history') {
    return <StudentHistoryFeature route={props.route} data={props.data} reload={props.reload} />;
  }
  if (id === 't.home') {
    return <TeacherHomeFeature route={props.route} data={props.data} reload={props.reload} />;
  }
  if (id === 't.classes') {
    return <TeacherClassesFeature route={props.route} data={props.data} reload={props.reload} />;
  }
  if (id === 't.overview') {
    return <TeacherOverviewFeature route={props.route} data={props.data} reload={props.reload} />;
  }

  // Document owned routes (Stage 2)
  if (
    id === 't.library' ||
    id === 't.libraryDocument' ||
    id === 't.documents' ||
    id === 's.documents' ||
    id === 's.reader' ||
    id === 's.notes'
  ) {
    return (
      <Document
        route={props.route}
        data={props.data}
        role={props.role}
        reload={props.reload}
        params={props.params}
        user={props.user}
      />
    );
  }

  // Tutor owned routes (Stage 2)
  if (id === 's.tutor' || id === 't.tutor') {
    return (
      <Tutor
        route={props.route}
        data={props.data}
        role={props.role}
        reload={props.reload}
        params={props.params}
        user={props.user}
      />
    );
  }

  if (intelligenceRoutes.has(id)) return <Intelligence {...props}/>;
  if (assessmentRoutes.has(id)) return <Assessment {...props}/>;
  if (assignmentRoutes.has(id)) return <Assignment {...props}/>;
  if (classroomAdminRoutes.has(id)) return <ClassroomAdmin {...props}/>;
  if (accountRoutes.has(id)) return <Accounts {...props}/>;

  // Learning owned routes (Stage 3)
  if (
    id.startsWith('s.practice') ||
    id.startsWith('s.assessment') ||
    id === 's.examAttempt' ||
    id === 's.receipt' ||
    id === 's.examResult' ||
    id.startsWith('s.assignment') ||
    id === 's.historyResult' ||
    id === 't.activities' ||
    id.startsWith('t.practice') ||
    id.startsWith('t.assessment') ||
    id.startsWith('t.assignment') ||
    id.startsWith('t.grading') ||
    id.startsWith('t.examGrading') ||
    id.startsWith('t.correction')
  ) {
    return (
      <Learning
        route={props.route}
        data={props.data}
        role={props.role}
        reload={props.reload}
        params={props.params}
        user={props.user}
      />
    );
  }

  // Subsequent domains fallback (Learning, Administration, Intelligence)
  const caps = props.route.capabilityIds;
  const Component = caps.includes('intelligence')
    ? Intelligence
    : caps.includes('learning')
    ? Learning
    : caps.includes('administration') || id.startsWith('a.')
    ? Administration
    : caps.includes('notification')
    ? Notification
    : caps.includes('social') || caps.includes('calendar')
    ? Social
    : Classroom;

  return (
    <Component
      route={props.route}
      data={props.data}
      role={props.role}
      reload={props.reload}
      params={props.params}
      user={props.user}
    />
  );
}
