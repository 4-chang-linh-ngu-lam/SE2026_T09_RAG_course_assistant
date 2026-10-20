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
    <div className="teacher-tutor-config-container space-y-6">
      {/* Top Description and Class Info */}
      <div className="card p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-bold">Chỉ dẫn sư phạm cho Trợ lý Lumi</h2>
            <p className="text-sm muted mt-1">
              Lớp: <strong>{classSummary?.name ?? params.classId}</strong> · Cập nhật gần nhất: {config.updatedAt}
            </p>
          </div>
          <span className="badge primary">D08 · Cấu hình lớp</span>
        </div>

        {/* Student Privacy Notice under Rules M2, C5, C6 */}
        <div className="notice-box info mt-4">
          <Icon name="info" />
          <p className="text-xs">
            <strong>Bảo vệ quyền riêng tư học sinh:</strong> {config.disclaimer}
          </p>
        </div>
      </div>

      {/* Main Config Form */}
      <form onSubmit={handleSave} className="card p-6 space-y-4">
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

        <div>
          <label htmlFor="tutorInstructionsArea" className="label font-semibold block mb-1">
            Nội dung chỉ dẫn phương pháp sư phạm:
          </label>
          <p className="text-xs muted mb-2">
            Gợi ý: Hướng dẫn Lumi ưu tiên cách tiếp cận từng bước, khuyến khích học sinh tự tìm tòi công thức, hoặc tập trung vào các dạng bài tập trọng tâm trong học kỳ.
          </p>
          <textarea
            id="tutorInstructionsArea"
            className="input w-full"
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
          <div className="flex justify-between items-center text-xs muted mt-1">
            <span>{isDirty ? '• Bạn có thay đổi chưa lưu' : 'Chưa có thay đổi mới'}</span>
            <span className={instructions.length > maxChars * 0.9 ? 'text-amber-600 font-semibold' : ''}>
              {instructions.length} / {maxChars} ký tự
            </span>
          </div>
        </div>

        <div className="flex justify-end gap-3 pt-4 border-t">
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
            className="button primary"
            disabled={isPending || !isDirty}
          >
            {isPending ? 'Đang lưu…' : 'Lưu chỉ dẫn'}
          </button>
        </div>
      </form>
    </div>
  );
}
