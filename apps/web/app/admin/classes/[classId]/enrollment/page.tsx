import { RouteScreen } from '@/components/route-screen';
export default async function Page({ params }: { params: Promise<Record<string, string>> }) {
  return <RouteScreen routeId="a.enrollment" params={await params} />;
}
