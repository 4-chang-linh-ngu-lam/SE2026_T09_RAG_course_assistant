export default function Home() {
  return <main><h1>RAG Course Assistant</h1><p>Monorepo Core skeleton — SE2026-T09</p><p>Core API: <a href={process.env.NEXT_PUBLIC_CORE_API_URL ?? "http://localhost:8000"}>Health & OpenAPI</a></p></main>;
}
