'use client';
import type { RouteDefinition } from '@/config/routes';
import type { Role, RouteParams, User, WorkspaceData } from '@/lib/domain';
import { StatePanel } from '@/components/ui';
import { NotificationCenter } from './notification-center';
import { useNotificationState } from './use-notification-state';

type Props = { data: WorkspaceData | null; role: Role; params: RouteParams; reload(): void; route?: RouteDefinition; user?: User };
function AuthorizedNotifications({ data, user, reload }: { data: WorkspaceData | null; user: User; reload(): void }) {
  const state = useNotificationState(data, user, reload);
  return <NotificationCenter {...state}/>;
}
export function NotificationFeature({ data, user, reload }: Props) {
  if (!user) return <StatePanel title="Đăng nhập để xem thông báo"/>;
  return <AuthorizedNotifications key={user.id} data={data} user={user} reload={reload}/>;
}
export { NotificationFeature as Feature };
