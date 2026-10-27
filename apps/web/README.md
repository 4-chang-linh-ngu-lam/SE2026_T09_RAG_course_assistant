# Lumi Web

Next.js frontend scaffold in the product monorepo. Route/layout coverage is not completion of the 104 designs. Feature ownership and unimplemented integrations are explicit in `docs/FRONTEND.md` and `src/lib/data/integrations.ts`.

Requires Node 22.17+ and npm. From `apps/web`:

```powershell
npm ci
if (!(Test-Path .env.local)) { Copy-Item .env.example .env.local }
npm run dev
```

Live is the default. Set server-only `CORE_API_URL` and `WEB_ORIGIN` in `.env.local`; browser requests use same-origin `/api/v1`. `WEB_ORIGIN` is the exact public web scheme/host/port, even behind Docker or a reverse proxy. Set Core `CORS_ORIGINS` to that same public origin and configure cookie security appropriately. No internal service credential belongs in the web app.

For an isolated UI preview: `npm run dev:mock`. Preview accounts and data exist only in `dev/mocks/fixtures.ts`; Student username `minh.anh10a1`, staff `ha.nguyen@lumi.example` / `nam.pham@lumi.example`. Enter any nonempty password in this development-only adapter. The preview banner is always shown; no email/file/grade/backend persistence occurs. Refreshing a tab loses the in-memory preview session.

```powershell
npm run check
npm run build
npm start
```

The production build and server reject mock mode. The live build selects the live adapter at compilation, checks product import boundaries, then scans served bundles for the fixture marker. Missing APIs, invalid responses and errors never return fixture data. See `docs/FRONTEND.md` for integration steps and limitations.
