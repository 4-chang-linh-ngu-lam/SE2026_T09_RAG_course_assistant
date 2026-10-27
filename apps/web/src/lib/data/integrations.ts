// Current repository, not the newer design snapshot: Classroom is still PROPOSED.
export const integrations = {
  identity: { status: 'contracted', owner: 'Core.Identity' },
  studentProvisioning: { status: 'contracted', owner: 'Core.Identity' },
  personalData: { status: 'contracted', owner: 'Core.Identity', operations: { listSelfRequests: 'contracted', createSelfRequest: 'contracted', downloadCopy: 'pending-contract', reviewRequests: 'pending-contract', processCopy: 'pending-contract' } },
  classroom: { status: 'pending-contract', owner: 'Core.Classroom' },
  social: { status: 'pending-contract', owner: 'Core.Social' },
  calendar: { status: 'pending-contract', owner: 'Core.Social' },
  notification: { status: 'pending-contract', owner: 'Core.Notification' },
  administration: { status: 'pending-contract', owner: 'Core.Administration' },
  bulkImport: { status: 'pending-contract', owner: 'Core.Administration' },
  document: { status: 'pending-contract', owner: 'Document' },
  tutor: { status: 'pending-contract', owner: 'AI' },
  learning: { status: 'pending-contract', owner: 'Learning' },
  intelligence: { status: 'pending-contract', owner: 'Learner Intelligence' },
} as const;
