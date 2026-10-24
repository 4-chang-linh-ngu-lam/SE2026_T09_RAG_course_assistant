/** Start only on a visible, online document. One-flight ownership stays with the caller. */
export function subscribeForegroundSync(refresh:()=>void, intervalMs=10000):()=>void {
  const refreshVisible=()=>{if(document.visibilityState==='visible'&&navigator.onLine)refresh();};
  const timer=window.setInterval(refreshVisible,intervalMs);
  window.addEventListener('focus',refreshVisible);
  window.addEventListener('online',refreshVisible);
  document.addEventListener('visibilitychange',refreshVisible);
  refreshVisible();
  return()=>{
    window.clearInterval(timer);
    window.removeEventListener('focus',refreshVisible);
    window.removeEventListener('online',refreshVisible);
    document.removeEventListener('visibilitychange',refreshVisible);
  };
}
