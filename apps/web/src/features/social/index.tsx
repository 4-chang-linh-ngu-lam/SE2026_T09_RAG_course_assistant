'use client';
import type { RouteDefinition } from '@/config/routes';
import type { Role, RouteParams, User, WorkspaceData } from '@/lib/domain';
import { WorkspaceFeature } from '@/features/shared/workspace-feature';
import { CalendarFeature } from './calendar';
import { ClassFeedFeature } from './feed';

export { CalendarFeature, ClassFeedFeature };

type Props = {
  route: RouteDefinition;
  data: WorkspaceData | null;
  role: Role;
  user: User;
  params: RouteParams;
  reload(): void;
};

export function SocialFeature(props: Props) {
  const id = props.route.id;
  if (id === 'account.calendar') {
    return <CalendarFeature data={props.data} role={props.role} params={props.params} reload={props.reload} isGlobal />;
  }
  if (id === 's.calendar' || id === 't.calendar') {
    return <CalendarFeature data={props.data} role={props.role} params={props.params} reload={props.reload} isGlobal={false} />;
  }
  if (id === 's.feed' || id === 't.feed') {
    return <ClassFeedFeature data={props.data} role={props.role} user={props.user} params={props.params} reload={props.reload} />;
  }
  return <WorkspaceFeature route={props.route} data={props.data} role={props.role} reload={props.reload} />;
}

export { SocialFeature as Feature };
