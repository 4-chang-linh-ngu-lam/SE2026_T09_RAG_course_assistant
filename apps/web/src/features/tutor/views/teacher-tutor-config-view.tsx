'use client';
import {useSession} from '@/components/session-provider';
import {useVolatileDraft} from '@/components/volatile-draft';
import {draftStore} from '@/lib/draft-store';
import { useState, useTransition, useEffect } from 'react';
import type { RouteDefinition } from '@/config/routes';
import type { RouteParams, TeacherTutorInstructionConfig, WorkspaceData } from '@/lib/domain';
import { adapter } from '@/lib/data';
import { StatePanel, Icon, useUnsavedChanges } from '@/components/ui';

type Props = {
  route: RouteDefinition;
  data: WorkspaceData | null;
  params: RouteParams;
  reload(): void;
};

export function TeacherTutorConfigView({ data, params, reload }: Props) {
  const config = data && data.kind === 'ready' ? data.teacherTutorConfig : undefined;
  const initialText = config?.instructions ?? '';
  const {user}=useSession();
  const draftKey=`${user?.id}:tutor-config:${params.classId}`;
  const [instructions, setInstructions] = useVolatileDraft(draftKey, initialText);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  // Synchronize when config data loads
  useEffect(() => {
    if (config?.instructions !== undefined) {
      setInstructions(draftStore.get<string>(draftKey) ?? config.instructions);
    }
  }, [config?.instructions, draftKey]);

  const isDirty = instructions !== initialText;
  useUnsavedChanges(isDirty);

  if (!data) {
    return <StatePanel busy title="Đang tải cấu hình chỉ dẫn trợ lý…" />;
  }

  if (data.kind === 'unavailable') {
    return (
      <StatePanel title="Dịch vụ cấu hình trợ lý chưa sẵn sàng" message={data.message}>
        <button type="button" className="button" onClick={reload}>
          Thử lại
        </button>
      </StatePanel>
    );
  }

  if (data.kind === 'empty' || !config) {
    return <StatePanel title="Không tìm thấy cấu hình lớp học" message={data.kind === 'empty' ? data.message : 'Dữ liệu cấu hình không khả dụng.'} />;
  }

  const maxChars = config.maxChars || 2000;
  const classSummary = data.classSummary;

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    if (!params.classId) return;
    setSaveError(null);
    setSaveSuccess(false);

    startTransition(async () => {
      try {
        await adapter.tutor.updateConfig(params.classId, instructions.trim());
        setSaveSuccess(true);
        reload();
      } catch (err) {
        setSaveError(err instanceof Error ? err.message : 'Có lỗi khi lưu cấu hình chỉ dẫn.');
      }
    });
  };

  const handleReset = () => {
    setInstructions(initialText);
    setSaveError(null);
    setSaveSuccess(false);
  };

  return (
    <div className="teacher-tutor-config-container">
      {/* Top Description and Class Info */}
      <div className="card tutor-config-card">
        <div className="tutor-config-header">
          <div>
            <h2 className="tutor-config-title">Chỉ dẫn sư phạm cho Trợ lý Lumi</h2>
            <p className="tutor-config-meta">
              Lớp: <strong>{classSummary?.name ?? params.classId}</strong> · Cập nhật gần nhất: {config.updatedAt}
            </p>
          </div>
          <span className="tutor-config-badge">Cấu hình lớp</span>
        </div>

        {/* Student Privacy Notice under Rules M2, C5, C6 */}
        <div className="notice-box info">
          <Icon name="info" />
          <p>
            <strong>Bảo vệ quyền riêng tư học sinh:</strong> {config.disclaimer}
          </p>
        </div>
      </div>

      {/* Main Config Form */}
      <form onSubmit={handleSave} className="card tutor-config-form">
        {saveSuccess && (
          <div className="notice success" role="status">
            Đã lưu cấu hình chỉ dẫn sư phạm thành công. Lumi sẽ áp dụng định hướng này cho các phản hồi trong lớp.
          </div>
        )}

        {saveError && (
          <div className="notice error" role="alert">
            {saveError}
          </div>
        )}

        <div className="tutor-config-field">
          <label htmlFor="tutorInstructionsArea" className="tutor-config-label">
            Nội dung chỉ dẫn phương pháp sư phạm:
          </label>
          <p className="tutor-config-hint">
            Gợi ý: Hướng dẫn Lumi ưu tiên cách tiếp cận từng bước, khuyến khích học sinh tự tìm tòi công thức, hoặc tập trung vào các dạng bài tập trọng tâm trong học kỳ.
          </p>
          <textarea
            id="tutorInstructionsArea"
            className="tutor-config-textarea"
            rows={8}
            maxLength={maxChars}
            value={instructions}
            onChange={e => {
              setInstructions(e.target.value);
              setSaveSuccess(false);
            }}
            placeholder="ví dụ: Khuyến khích học sinh tự tính toán tọa độ đỉnh và tự lập bảng biến thiên. Không giải tắt hoặc đưa ngay đáp án cuối cùng…"
            disabled={isPending}
          />
          <div className="tutor-config-counter-row">
            <span>{isDirty ? '• Bạn có thay đổi chưa lưu' : 'Chưa có thay đổi mới'}</span>
            <span className={`tutor-config-char-count ${instructions.length > maxChars * 0.9 ? 'is-near-limit' : ''}`}>
              {instructions.length} / {maxChars} ký tự
            </span>
          </div>
        </div>

        <div className="tutor-config-actions">
          <button
            type="button"
            className="button secondary"
            onClick={handleReset}
            disabled={isPending || !isDirty}
          >
            Khôi phục ban đầu
          </button>
          <button
            type="submit"
            className="button primary tutor-action-primary"
            disabled={isPending || !isDirty}
          >
            {isPending ? 'Đang lưu…' : 'Lưu chỉ dẫn'}
          </button>
        </div>
      </form>
    </div>
  );
}
