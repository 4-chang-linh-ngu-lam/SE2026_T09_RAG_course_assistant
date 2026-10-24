'use client';
import type { RouteDefinition } from '@/config/routes';
import type { Role, RouteParams, User, WorkspaceData } from '@/lib/domain';
import { WorkspaceFeature } from '@/features/shared/workspace-feature';
import { TeacherLibraryView } from './views/teacher-library-view';
import { TeacherLibraryDocumentView } from './views/teacher-library-document-view';
import { TeacherClassDocumentsView } from './views/teacher-class-documents-view';
import { StudentClassDocumentsView } from './views/student-class-documents-view';
import { StudentReaderView } from './views/student-reader-view';
import { StudentNotesView } from './views/student-notes-view';
import {useDocumentWorkspace} from './use-document-workspace';

export {
  TeacherLibraryView,
  TeacherLibraryDocumentView,
  TeacherClassDocumentsView,
  StudentClassDocumentsView,
  StudentReaderView,
  StudentNotesView,
};

type Props = {
  route: RouteDefinition;
  data: WorkspaceData | null;
  role: Role;
  reload(): void;
  params?: RouteParams;
  user?: User;
};

export function DocumentFeature(props: Props) {
  const id = props.route.id;
  const params = props.params ?? {};
  const workspace=useDocumentWorkspace(id,params);
  props={...props,data:workspace.data,reload:workspace.reload};

  if (id === 't.library') return <TeacherLibraryView route={props.route} data={props.data} reload={props.reload} />;
  if (id === 't.libraryDocument') return <TeacherLibraryDocumentView route={props.route} data={props.data} reload={props.reload} />;
  if (id === 't.documents') return <TeacherClassDocumentsView route={props.route} data={props.data} params={params} reload={props.reload} />;
  if (id === 's.documents') return <StudentClassDocumentsView route={props.route} data={props.data} params={params} reload={props.reload} />;
  if (id === 's.reader') return <StudentReaderView route={props.route} data={props.data} params={params} reload={props.reload} />;
  if (id === 's.notes') return <StudentNotesView route={props.route} data={props.data} reload={props.reload} />;

  return <WorkspaceFeature {...props} />;
}

export { DocumentFeature as Feature };
