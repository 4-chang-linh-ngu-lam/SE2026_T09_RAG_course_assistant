import { RouteScreen } from '@/components/route-screen';
export default async function Page({ params }: { params: Promise<Record<string, string>> }) {
  return <RouteScreen routeId="s.practiceResult" params={await params} />;
}
