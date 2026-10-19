import { createCoreProxy } from '@/lib/api/proxy';
export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
const proxy = createCoreProxy(() => process.env.CORE_API_URL, fetch, () => process.env.WEB_ORIGIN);
async function handler(request: Request, context: { params: Promise<{ path: string[] }> }) { return proxy(request, (await context.params).path); }
export { handler as GET, handler as POST, handler as PATCH };
