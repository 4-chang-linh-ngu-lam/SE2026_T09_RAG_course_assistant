import type {DataAdapter} from './port';
import type {createLiveCoreSession} from './live-identity';
import type {NotificationItem,WorkspaceData} from '../domain';
import {ApiError} from '../api/errors';
import {decodeMutation} from '../api/decoders';
import {decodeNotificationPage,decodeNotificationRead} from '../api/notification-decoders';

type Session = Pick<ReturnType<typeof createLiveCoreSession>,'authenticated'|'getActorId'>;
export function createLiveNotifications(session: Session) {
  const port: DataAdapter['notifications'] = {
    markAsRead(notificationId) {
      return session.authenticated(async request => {
        decodeMutation(value => decodeNotificationRead(value,notificationId), await request('markNotificationRead',{notificationId}));
      },true);
    },
    markAllAsRead() { return session.authenticated(async request => { await request('markAllNotificationsRead'); },true); },
  };
  function load(signal?: AbortSignal): Promise<WorkspaceData> {
    const deadline = AbortSignal.timeout(15000);
    const boundedSignal = signal ? AbortSignal.any([signal,deadline]) : deadline;
    return session.authenticated(async request => {
      const actorId = session.getActorId();
      if (!actorId) throw new ApiError('SESSION_CHANGED','Phiên đăng nhập đã thay đổi. Hãy tải lại.',401);
      const items: NotificationItem[] = [], cursors = new Set<string>(), ids = new Set<string>();
      let cursor: string|undefined, unreadCount = 0;
      do {
        if (boundedSignal.aborted) throw new ApiError('CONNECTION_ERROR','Chưa tải được đầy đủ thông báo. Vui lòng thử lại.',0);
        const page = decodeNotificationPage(await request('notifications',{cursor,limit:100,signal:boundedSignal}),actorId);
        for (const item of page.items) {
          if (ids.has(item.id)) throw new ApiError('CONTRACT_MISMATCH','Trang thông báo bị lặp. Vui lòng tải lại.');
          ids.add(item.id);items.push(item);
        }
        unreadCount = page.unreadCount;
        if (page.nextCursor && (cursors.has(page.nextCursor) || !page.items.length || cursors.size >= 99)) throw new ApiError('CONTRACT_MISMATCH','Chưa tải được đầy đủ thông báo. Vui lòng tải lại.');
        cursor = page.nextCursor ?? undefined;
        if (cursor) cursors.add(cursor);
      } while (cursor);
      return {kind:'ready',notifications:items,notificationUnreadCount:unreadCount};
    });
  }
  return {port,load};
}
