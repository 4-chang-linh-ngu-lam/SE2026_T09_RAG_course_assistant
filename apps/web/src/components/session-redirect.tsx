'use client';
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useSession } from './session-provider';
import { Brand, StatePanel } from './ui';
import { homeFor } from '@/config/routes';
export function SessionRedirect() {
  const session = useSession(), router = useRouter();
  useEffect(() => { if (session.status === 'authenticated' && session.user) router.replace(homeFor(session.user.roles)); else if (session.status === 'signed-out') router.replace('/login'); }, [session.status, session.user, router]);
  return <main className="standalone"><Brand/><StatePanel busy={session.status === 'loading'} title={session.status === 'unavailable' ? 'Chưa thể kiểm tra phiên' : 'Đang mở không gian học tập…'} message={session.error ?? undefined}>{session.status === 'unavailable' && <><button className="button" onClick={() => void session.reload()}>Thử lại</button><Link href="/login">Đăng nhập</Link></>}</StatePanel></main>;
}
