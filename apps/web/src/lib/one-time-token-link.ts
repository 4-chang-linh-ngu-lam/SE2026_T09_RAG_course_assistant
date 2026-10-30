export type OneTimeTokenLink = { token: string | null; cleanUrl: string };

export function consumeOneTimeTokenLink(url: URL): OneTimeTokenLink {
  const fragment = new URLSearchParams(url.hash.startsWith('#') ? url.hash.slice(1) : url.hash);
  const token = fragment.get('token') || url.searchParams.get('token');
  if (!token) return { token: null, cleanUrl: `${url.pathname}${url.search}${url.hash}` };

  fragment.delete('token');
  url.searchParams.delete('token');
  url.hash = fragment.toString() ? `#${fragment.toString()}` : '';
  return { token, cleanUrl: `${url.pathname}${url.search}${url.hash}` };
}
