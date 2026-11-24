import type { Metadata } from 'next';
import { LandingPage } from '@/features/landing/landing-page';

export const metadata: Metadata = {
  title: 'Giới thiệu · Không gian học tập phổ thông',
  description: 'Lumi kết nối lớp học, bảng tin, lịch học tập và trợ giảng AI có dẫn nguồn trong một không gian học tập chuẩn mực.',
};

export default function Page() {
  return <LandingPage />;
}
