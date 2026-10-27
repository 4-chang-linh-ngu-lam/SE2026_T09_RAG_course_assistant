import type { ClassSummary, TeacherHomeOverview } from './domain';

// Class cards do not contain a distinct-school roster or grading queue.
// Missing aggregate metrics must remain unknown rather than be invented or summed.
export function teachingWorkload(classes: readonly ClassSummary[], stats?: TeacherHomeOverview['stats']) {
  return {
    totalClasses: stats?.totalClasses ?? classes.length,
    totalStudents: stats?.totalStudents ?? null,
    pendingGrading: stats?.pendingGrading ?? null,
  };
}

// Dashboard actions describe current teaching work. Archive/history cards remain
// visible separately; their old discussions must not advertise new replies.
export function operationalTeachingOverview(
  classes: readonly ClassSummary[],
  overview?: Pick<TeacherHomeOverview, 'todaySchedule' | 'recentDiscussions'>,
) {
  const active = new Set(classes.filter(item => item.status === 'ACTIVE').map(item => item.id));
  return {
    schedule: (overview?.todaySchedule ?? []).filter(item => !item.classId || active.has(item.classId)),
    discussions: (overview?.recentDiscussions ?? []).filter(item => active.has(item.classId)),
  };
}
