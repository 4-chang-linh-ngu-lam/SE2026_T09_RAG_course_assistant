'use client';
export default function ErrorPage({ reset }: { reset(): void }) { return <main className="standalone"><h1>Chưa thể mở nội dung</h1><p>Vui lòng thử lại sau.</p><button className="button" onClick={reset}>Thử lại</button></main>; }
