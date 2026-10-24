'use client';
import Link from 'next/link';
import type { Role, User } from '@/lib/domain';
import { Icon } from '@/components/ui';
export const roleLabel: Record<Role, string> = { ADMIN: 'Quản trị viên', LECTURER: 'Giáo viên', STUDENT: 'Học sinh' };
export const statusLabel: Record<User['status'], string> = { ACTIVE: 'Đang hoạt động', PENDING_VERIFICATION: 'Chờ kích hoạt', LOCKED: 'Đã khóa' };
export function Status({ value }: { value: User['status'] }) { return <span className={`accounts-status accounts-status-${value.toLowerCase()}`}>{statusLabel[value]}</span>; }
export function PageLinks() { return <div className="accounts-actions"><Link className="button" href="/admin/accounts"><Icon name="arrow"/>Danh sách tài khoản</Link></div>; }
