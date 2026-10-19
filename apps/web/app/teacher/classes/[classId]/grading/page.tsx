import { RouteScreen } from '@/components/route-screen';
export default async function Page({ params }: { params: Promise<Record<string, string>> }) {
  return <RouteScreen routeId="t.gradingQueue" params={await params} />;
}
