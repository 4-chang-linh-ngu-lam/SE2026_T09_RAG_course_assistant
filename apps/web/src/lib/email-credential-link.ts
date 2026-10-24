/** Consume an email credential into memory; never keep it in navigation state. */
export function readEmailCredentialLink(href:string):{token:string;cleanPath:string}{
  const url=new URL(href);
  const fragment=new URLSearchParams(url.hash.slice(1));
  const candidate=fragment.get('token')??url.searchParams.get('token')??'';
  fragment.delete('token');
  url.searchParams.delete('token');
  url.hash=fragment.toString();
  return {token:candidate.length<=256?candidate:'',cleanPath:url.pathname+url.search+url.hash};
}
