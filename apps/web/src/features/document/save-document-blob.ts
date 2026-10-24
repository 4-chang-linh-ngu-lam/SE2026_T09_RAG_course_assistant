/** Local browser download after the authenticated byte request has succeeded. */
export function saveDocumentBlob(blob:Blob,filename:string){
  const url=URL.createObjectURL(blob),link=document.createElement('a');
  link.href=url;link.download=filename.replace(/[\\/\u0000-\u001f]/g,'_');
  document.body.append(link);link.click();link.remove();
  window.setTimeout(()=>URL.revokeObjectURL(url),30000);
}
