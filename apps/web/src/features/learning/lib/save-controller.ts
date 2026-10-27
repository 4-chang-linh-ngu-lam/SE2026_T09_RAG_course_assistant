import { ApiError, type Outcome } from '@/lib/api/errors';
import type { PracticeAnswer, PracticeQuestion } from '@/lib/domain';

export type SaveControllerStatus = 'idle' | 'saving' | 'saved' | 'error';

export type SaveControllerOptions = {
  saveFn: (answers: Record<string, PracticeAnswer>) => Promise<{ savedAt: string }>;
  onStatusChange?: (status: SaveControllerStatus, message?: string) => void;
  onError?: (error: unknown, outcome: Outcome) => void;
  onAcknowledged?: (answers: Record<string, PracticeAnswer>, savedAt: string) => void;
};

export function isAnswerComplete(question: PracticeQuestion, answer?: PracticeAnswer): boolean {
  if (!answer || answer.questionId !== question.id) return false;
  switch (question.type) {
    case 'single_choice': {
      if (!answer.singleChoiceValue || typeof answer.singleChoiceValue !== 'string') return false;
      const val = answer.singleChoiceValue.trim();
      if (!val) return false;
      if (!Array.isArray(question.options) || question.options.length === 0) return false;
      return question.options.some(opt => opt.id === val);
    }
    case 'multiple_choice': {
      if (!Array.isArray(answer.multipleChoiceValues) || answer.multipleChoiceValues.length === 0) return false;
      if (!Array.isArray(question.options) || question.options.length === 0) return false;
      const validOptIds = new Set(question.options.map(o => o.id));
      return answer.multipleChoiceValues.every(val => typeof val === 'string' && validOptIds.has(val));
    }
    case 'true_false': {
      const statements = question.statements ?? [];
      if (statements.length === 0) return false;
      if (!answer.trueFalseValues || typeof answer.trueFalseValues !== 'object') return false;
      return statements.every(stmt => typeof answer.trueFalseValues?.[stmt.id] === 'boolean');
    }
    case 'short_answer':
      return Boolean(answer.shortAnswerValue && typeof answer.shortAnswerValue === 'string' && answer.shortAnswerValue.trim() !== '');
    default:
      return false;
  }
}

export class SaveController {
  private inFlight = false;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private sentAnswers: Record<string, PracticeAnswer> | null = null;
  private queuedAnswers: Record<string, PracticeAnswer> | null = null;
  private pendingAnswers: Record<string, PracticeAnswer> = {};
  private flushResolvers: Array<{ resolve: () => void; reject: (err: unknown) => void }> = [];
  private disposed = false;
  private blocked = false;
  private lastError: unknown = null;
  private lastSavedAnswers: Record<string, PracticeAnswer> | null = null;

  constructor(private options: SaveControllerOptions) {}

  public isSaving(): boolean {
    return this.inFlight;
  }

  public hasQueuedEdits(): boolean {
    return this.queuedAnswers !== null;
  }

  public isBlocked(): boolean {
    return this.blocked;
  }

  public isDisposed(): boolean {
    return this.disposed;
  }

  public getLastSavedAnswers(): Record<string, PracticeAnswer> | null {
    return this.lastSavedAnswers ? structuredClone(this.lastSavedAnswers) : null;
  }

  public getPendingAnswers(): Record<string, PracticeAnswer> {
    return structuredClone(this.pendingAnswers);
  }

  public getLastError(): unknown {
    return this.lastError;
  }

  public block(err?: unknown): void {
    this.cancelTimer();
    this.blocked = true;
    this.lastError = err ?? new Error('SaveController is in error state');
  }

  public unblockAndReconcile(authoritativeAnswers?: Record<string, PracticeAnswer>): void {
    this.cancelTimer();
    this.queuedAnswers = null;
    this.blocked = false;
    this.lastError = null;
    if (authoritativeAnswers) {
      this.lastSavedAnswers = structuredClone(authoritativeAnswers);
      this.pendingAnswers = structuredClone(authoritativeAnswers);
    }
  }

  public queueSave(answers: Record<string, PracticeAnswer>, delayMs = 0): void {
    if (this.disposed) return;
    const cloned = structuredClone(answers);
    this.pendingAnswers = cloned;
    this.queuedAnswers = JSON.stringify(cloned) === JSON.stringify(this.sentAnswers ?? this.lastSavedAnswers) ? null : cloned;

    // If blocked due to previous error/unknown outcome, do NOT trigger automatic write
    if (this.blocked) {
      return;
    }

    if (!this.inFlight) {
      this.cancelTimer();
      if (!this.queuedAnswers) return;
      if (delayMs > 0) this.timer = setTimeout(() => { this.timer = null; void this.executeNext(); }, delayMs);
      else void this.executeNext();
    }
  }

  private cancelTimer(): void { if (this.timer !== null) { clearTimeout(this.timer); this.timer = null; } }

  /** Explicit action barrier: restored local edits must be ACKed before check/finish. */
  public async flushAnswers(answers: Record<string, PracticeAnswer>): Promise<void> {
    if (this.blocked) throw this.lastError ?? new Error('SaveController is in error state');
    this.queueSave(answers);
    await this.flush();
    if (JSON.stringify(this.lastSavedAnswers) !== JSON.stringify(answers)) throw new Error('Câu trả lời chưa được xác nhận lưu.');
  }

  private async executeNext(): Promise<void> {
    if (this.disposed) {
      this.inFlight = false;
      this.rejectFlush(new Error('SaveController has been disposed'));
      return;
    }

    if (this.blocked) {
      this.inFlight = false;
      this.rejectFlush(this.lastError ?? new Error('SaveController is in error state'));
      return;
    }

    if (!this.queuedAnswers) {
      this.inFlight = false;
      this.resolveFlush();
      return;
    }

    this.inFlight = true;
    const currentPayload = this.queuedAnswers;
    this.sentAnswers = currentPayload;
    this.queuedAnswers = null;
    this.options.onStatusChange?.('saving', 'Đang lưu...');

    try {
      const res = await this.options.saveFn(currentPayload);
      if (this.disposed) {
        this.inFlight = false;
        this.rejectFlush(new Error('SaveController has been disposed'));
        return;
      }
      this.lastSavedAnswers = currentPayload;
      this.sentAnswers = null;
      this.options.onAcknowledged?.(structuredClone(currentPayload), res.savedAt);
      // Only announce overall saved when latest queued edit ACKed;
      // an older ACK cannot mark latest edits saved!
      if (this.queuedAnswers === null) {
        this.options.onStatusChange?.('saved', `Đã lưu: ${res.savedAt}`);
      }
    } catch (err: unknown) {
      if (this.disposed) {
        this.inFlight = false;
        this.rejectFlush(new Error('SaveController has been disposed'));
        return;
      }
      this.blocked = true;
      this.lastError = err;
      // Queued values are complete snapshots; retain failed payload if no newer edits,
      // and do not merge an older failed snapshot into newer answers.
      if (this.queuedAnswers === null) {
        this.queuedAnswers = currentPayload;
      }
      const outcome: Outcome = err instanceof ApiError ? err.outcome : 'rejected';
      const msg = err instanceof Error ? err.message : 'Lỗi khi lưu bài';
      this.options.onStatusChange?.('error', msg);
      this.options.onError?.(err, outcome);
      this.inFlight = false;
      this.rejectFlush(err);
      return;
    } finally {
      this.sentAnswers = null;
      if (this.disposed) {
        this.inFlight = false;
        this.rejectFlush(new Error('SaveController has been disposed'));
        return;
      }

      if (this.blocked) {
        this.inFlight = false;
        return;
      }

      if (this.queuedAnswers !== null) {
        void this.executeNext();
      } else {
        this.inFlight = false;
        this.resolveFlush();
      }
    }
  }

  private resolveFlush(): void {
    if (this.flushResolvers.length > 0) {
      const resolvers = [...this.flushResolvers];
      this.flushResolvers = [];
      for (const item of resolvers) {
        item.resolve();
      }
    }
  }

  private rejectFlush(err: unknown): void {
    if (this.flushResolvers.length > 0) {
      const resolvers = [...this.flushResolvers];
      this.flushResolvers = [];
      for (const item of resolvers) {
        item.reject(err);
      }
    }
  }

  public flush(): Promise<void> {
    this.cancelTimer();
    if (this.disposed) {
      return Promise.reject(new Error('SaveController has been disposed'));
    }
    if (this.blocked || this.lastError) {
      return Promise.reject(this.lastError ?? new Error('SaveController is in error state'));
    }
    if (!this.inFlight && !this.queuedAnswers) {
      return Promise.resolve();
    }
    const pending = new Promise<void>((resolve, reject) => {
      this.flushResolvers.push({ resolve, reject });
    });
    if (!this.inFlight) void this.executeNext();
    return pending;
  }

  public dispose(): void {
    this.disposed = true;
    this.cancelTimer();
    this.queuedAnswers = null;
    this.rejectFlush(new Error('SaveController has been disposed'));
  }
}
