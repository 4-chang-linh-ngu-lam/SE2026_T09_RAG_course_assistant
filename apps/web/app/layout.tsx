import type { ReactNode } from 'react';
import type { Metadata } from 'next';
import { SessionProvider } from '@/components/session-provider';
import './globals.css';
export const metadata: Metadata = { title: { default: 'Lumi · Học sáng hơn mỗi ngày', template: '%s · Lumi' }, description: 'Không gian học tập phổ thông Lumi' };
export default function RootLayout({ children }: { children: ReactNode }) { return <html lang="vi"><body><a className="skip-link" href="#main-content">Đến nội dung chính</a><SessionProvider>{children}</SessionProvider></body></html>; }
