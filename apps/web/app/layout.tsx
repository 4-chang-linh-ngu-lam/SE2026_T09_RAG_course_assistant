import type { ReactNode } from "react";
export const metadata = { title: "RAG Course Assistant", description: "SE2026-T09" };
export default function RootLayout({ children }: { children: ReactNode }) {
  return <html lang="vi"><body style={{fontFamily:"system-ui",margin:"3rem"}}>{children}</body></html>;
}
