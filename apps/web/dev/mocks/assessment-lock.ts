// Dev-only helper for Rule D6 official assessment lock
// Scoped strictly by actor, class, and attempt, shared with future Learning domain without query flags or global class Sets

type LockEntry = {
  locked: boolean;
  userId: string;
  classId: string;
  attemptId: string;
  title?: string;
  isActive?: () => boolean;
};

const assessmentLocks = new Map<string, LockEntry>();

export type SetAssessmentLockParams = {
  userId: string;
  classId: string;
  attemptId: string;
  title?: string;
  isActive?: () => boolean;
  locked: boolean;
};

/**
 * Sets or clears an assessment lock scoped strictly by actor, class, and attempt.
 * Legacy wildcard/class-global path has been completely removed to avoid cross-actor leaks.
 */
export function setMockAssessmentLock(target: SetAssessmentLockParams): void {
  const key = `${target.userId}:${target.classId}:${target.attemptId}`;

  if (!target.locked) {
    assessmentLocks.delete(key);
  } else {
    assessmentLocks.set(key, {
      locked: true,
      userId: target.userId,
      classId: target.classId,
      attemptId: target.attemptId,
      isActive: target.isActive,
      title: target.title ?? 'Kiểm tra chính thức',
    });
  }
}

/**
 * Checks if official assessment lock is currently active for a given student and class.
 * Scoped strictly to the specific student - never leaks to other students in the class.
 */
function current(entry: LockEntry): boolean {
  if (!entry.isActive) return entry.locked;
  try {
    if (entry.isActive()) return true;
    assessmentLocks.delete(`${entry.userId}:${entry.classId}:${entry.attemptId}`);
    return false;
  } catch { return true; } // Unknown authority must not grant Tutor access.
}

export function isMockAssessmentLocked(userId: string, classId: string): boolean {
  for (const entry of assessmentLocks.values()) {
    if (entry.userId === userId && entry.classId === classId && current(entry)) {
      return true;
    }
  }
  return false;
}

/**
 * Retrieves assessment lock metadata if active for the given student and class.
 */
export function getMockAssessmentLockInfo(userId: string, classId: string): { locked: boolean; title?: string; attemptId?: string } | null {
  for (const entry of assessmentLocks.values()) {
    if (entry.userId === userId && entry.classId === classId && current(entry)) {
      return {
        locked: true,
        title: entry.title,
        attemptId: entry.attemptId,
      };
    }
  }
  return null;
}

/**
 * Clears all assessment locks (e.g. for test teardown).
 */
export function clearMockAssessmentLocks(): void {
  assessmentLocks.clear();
}
