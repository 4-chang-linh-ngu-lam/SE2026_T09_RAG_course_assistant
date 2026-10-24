// 63 approved Core operations including 8 scoped metadata reads; other services
// still require their own contracts. No fixture fallback in live workspaces.
export const integrations = {
  identity: { status: 'contracted', owner: 'Core.Identity' },
  studentProvisioning: { status: 'contracted', owner: 'Core.Identity' },
  personalData: { status: 'contracted', owner: 'Core.Identity', operations: { listSelfRequests: 'contracted', createSelfRequest: 'contracted', downloadCopy: 'pending-contract', reviewRequests: 'contracted', processCopy: 'pending-contract' }, adminWorkspace:'live-review-only' },
  classroom: { status: 'contracted', owner: 'Core.Classroom', workspace:'live-core', home:'live-class-list', overview:'live-core-metadata', personalHistory:'pending-service-contracts', unsupportedMutations:['catalog-edit','class-rename','enrollment-override'] },
  social: { status: 'contracted', owner: 'Core.Social', workspace:'live' },
  calendar: { status: 'contracted', owner: 'Core.Social', workspace:'live' },
  notification: { status: 'contracted', owner: 'Core.Notification', operations: {listSelf:'contracted',markOneRead:'contracted',markAllRead:'contracted'} },
  administration: { status: 'contracted', owner: 'Core.Administration', auditWorkspace:'live', accountsWorkspace:'live', staffInviteForm:'live', blockedReads:['staff-invitations'], accountSave:'separate-status-role-transactions' },
  bulkImport: { status: 'contracted', owner: 'Core.Administration', workspace:'live-original-file', history:'pending-contract', wire:'file-bytes-preview-id-one-time-disclosure' },
  document: { status: 'contracted', owner: 'Document', workspace:'live-document', contract:'TASK-017-v1', unavailableDependencies:['AI-index-TASK-018'] },
  tutor: { status: 'pending-contract', owner: 'AI' },
  learning: { status: 'pending-contract', owner: 'Learning' },
  intelligence: { status: 'pending-contract', owner: 'Learner Intelligence' },
} as const;
