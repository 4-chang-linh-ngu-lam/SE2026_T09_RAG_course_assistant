// Types only. Runtime resolution belongs exclusively to next.config.mjs.
declare module '@data-adapter' {
  export const adapter: import('./port').DataAdapter;
}
