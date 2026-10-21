import type { AssessmentAnswers, AssessmentAttempt } from '@/lib/assessment';

import {sameAssessmentAnswers as same} from './answer-equality';

/** Serial latest-snapshot writes. Unknown ACKs stay blocked until an authoritative read. */
export class AssessmentAnswerSaver {
  private queued: AssessmentAnswers | null = null;
  private activePayload: AssessmentAnswers | null = null;
  private active: Promise<void> | null = null;
  private confirmed: AssessmentAnswers | null;
  private failed: unknown = null;
  private disposed = false;
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private revision: number,
    private write: (answers: AssessmentAnswers, revision: number) => Promise<AssessmentAttempt>,
    private ack: (attempt: AssessmentAttempt, pending: boolean) => void,
    initialAnswers?: AssessmentAnswers,
    private onError?: (error: unknown) => void,
  ) { this.confirmed = initialAnswers ? structuredClone(initialAnswers) : null; }

  enqueue(answers: AssessmentAnswers, delayMs = 0): void {
    if (this.disposed) throw new Error('Lượt làm đã đóng.');
    const snapshot = structuredClone(answers);
    // A -> B -> A while A is being written needs no second write of A.
    this.queued = same(snapshot, this.activePayload ?? this.confirmed) ? null : snapshot;
    if (this.active || this.failed) return;
    this.pause();
    if (!this.queued) return;
    if (delayMs > 0) this.timer = setTimeout(() => { this.timer = null; this.start(); }, delayMs);
    else this.start();
  }

  /** Stop a scheduled autosave before a read; keep local edits and any active write. */
  pause(): void { if (this.timer !== null) { clearTimeout(this.timer); this.timer = null; } }

  private start(): void {
    if (this.active || this.failed || this.disposed || !this.queued) return;
    this.active = this.run().finally(() => {
      this.active = null;
      if (this.queued && !this.failed && !this.disposed) this.start();
    });
  }

  private async run(): Promise<void> {
    while (this.queued && !this.disposed && !this.failed) {
      const snapshot = this.queued;
      this.queued = null;
      this.activePayload = snapshot;
      try {
        const attempt = await this.write(snapshot, this.revision);
        if (this.disposed) return;
        this.revision = attempt.savedRevision;
        this.confirmed = structuredClone(attempt.savedAnswers ?? snapshot);
        if (same(this.queued, this.confirmed)) this.queued = null;
        this.activePayload = null;
        this.ack(attempt, this.queued !== null);
      } catch (error) {
        this.failed = error;
        if (!this.queued) this.queued = snapshot;
        if (!this.disposed) this.onError?.(error);
      } finally { this.activePayload = null; }
    }
  }

  async waitForIdle(): Promise<void> { while (this.active) await this.active; }

  async flush(): Promise<void> {
    if (this.disposed) throw new Error('Lượt làm đã đóng.');
    this.pause();
    this.start();
    await this.waitForIdle();
    if (this.disposed) throw new Error('Lượt làm đã đóng.');
    if (this.failed) throw this.failed;
  }

  reconcile(revision: number, savedAnswers?: AssessmentAnswers): void {
    if (this.active) throw new Error('Đang chờ phản hồi lưu.');
    this.pause();
    this.revision = revision;
    this.failed = null;
    if (savedAnswers) {
      this.confirmed = structuredClone(savedAnswers);
      if (same(this.queued, this.confirmed)) this.queued = null;
    }
    // Reconciliation never implicitly replays an unknown write.
  }

  get needsReconcile(): boolean { return this.failed !== null; }
  get currentRevision(): number { return this.revision; }
  get isSaving(): boolean { return this.active !== null || this.timer !== null; }
  get hasPending(): boolean { return this.queued !== null || this.active !== null || this.timer !== null; }
  dispose(): void { this.disposed = true; this.pause(); this.queued = null; }
}
