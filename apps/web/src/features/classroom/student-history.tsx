'use client';
import { useState } from 'react';
import Link from 'next/link';
import type { RouteDefinition } from '@/config/routes';
import type { WorkspaceData } from '@/lib/domain';
import { StatePanel, Icon } from '@/components/ui';

type Props = {
  route: RouteDefinition;
  data: WorkspaceData | null;
  reload(): void;
};

export function StudentHistoryFeature({ route: _route, data, reload }: Props) {
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);

  if (!data) {
    return <StatePanel busy title="Đang tải dữ liệu lịch sử lớp học…" />;
  }

  if (data.kind === 'unavailable') {
    return (
      <StatePanel
        title="Dịch vụ lưu trữ lịch sử chưa sẵn sàng"
        message={data.message}
      >
        <button className="button" onClick={reload}>
          Thử lại
        </button>
      </StatePanel>
    );
  }

  if (data.kind === 'empty') {
    return (
      <StatePanel
        title="Chưa có dữ liệu lịch sử"
        message={data.message}
      />
    );
  }

  const history = data.historyData;
  const summary = history?.summary ?? data.classSummary;
  const conversations = history?.conversations ?? [];
  const notes = history?.notes ?? [];

  const activeConversation = conversations.find(c => c.id === selectedConversationId) ?? conversations[0];

  return (
    <div className="student-history-container">
      {/* Return Navigation */}
      <div className="history-breadcrumb-row">
        <Link className="link-button" href="/student/classes">
          <Icon name="arrowLeft" /> Quay lại danh sách lớp học
        </Link>
      </div>

      {/* Class Archive Status Banner */}
      <div className="card history-status-banner warning">
        <div className="banner-icon">
          <Icon name="lock" />
        </div>
        <div className="banner-content">
          <h3>
            {summary?.membershipStatus === 'ENDED'
              ? 'Ghi danh đã kết thúc · Lịch sử cá nhân'
              : 'Lớp học trong trạng thái lưu trữ / Lịch sử'}
          </h3>
          <p>
            {history?.historyNotice ??
              'Lớp học này đã kết thúc hoặc bạn đã hoàn thành chương trình học. Dữ liệu học tập và các đoạn hội thoại trước đây được giữ lại ở chế độ CHỈ ĐỌC để tra cứu. Các tính năng tương tác trực tiếp (hỏi Lumi trực tiếp, nộp bài, thảo luận bảng tin) đã đóng theo quy định bảo lưu.'}
          </p>
        </div>
      </div>

      {/* Class Meta Overview */}
      <div className="card history-meta-card">
        <div className="history-meta-top">
          <span className="tag default">{summary?.code ?? 'LỚP HỌC'}</span>
          <span className="badge warning">
            {summary?.membershipStatus === 'ENDED' ? 'Đã kết thúc ghi danh' : 'Đã lưu trữ'}
          </span>
        </div>
        <h2>{summary?.name ?? 'Thông tin lớp học'}</h2>
        <div className="history-meta-details muted text-sm">
          <span>Giáo viên: {summary?.teacherName ?? 'Chưa rõ'}</span>
          <span>·</span>
          <span>Thông tin: {summary?.metadata ?? 'Năm học cũ'}</span>
        </div>
      </div>

      {/* Two Column Layout: Past Chat Conversations & Notes */}
      <div className="history-two-col">
        {/* Left: Past Conversations Master-Detail */}
        <section className="history-section history-conversations-section">
          <div className="section-header">
            <div>
              <h3>Hội thoại đã lưu với Lumi ({conversations.length})</h3>
              <p className="muted text-sm">Tra cứu câu hỏi và giải đáp từ các buổi học trước</p>
            </div>
          </div>

          {conversations.length === 0 ? (
            <div className="card empty-card">
              <p className="muted">Không có hội thoại nào được lưu trong lớp này.</p>
            </div>
          ) : (
            <div className="history-conv-master-detail">
              {/* Conversation Selector List */}
              <div className="history-conv-list">
                {conversations.map(conv => (
                  <button
                    key={conv.id}
                    type="button"
                    className={`conv-list-item ${activeConversation?.id === conv.id ? 'active' : ''}`}
                    onClick={() => setSelectedConversationId(conv.id)}
                  >
                    <div className="conv-item-top">
                      <span className="conv-title">{conv.title}</span>
                      <span className="conv-date muted text-xs">{conv.date}</span>
                    </div>
                    <p className="conv-preview muted text-xs">{conv.preview}</p>
                  </button>
                ))}
              </div>

              {/* Conversation Transcript (Read-Only) */}
              <div className="card history-conv-viewer">
                {activeConversation ? (
                  <>
                    <div className="viewer-header">
                      <div>
                        <h4>{activeConversation.title}</h4>
                        <span className="muted text-xs">Ngày: {activeConversation.date} · Chế độ chỉ đọc</span>
                      </div>
                      <span className="badge info text-xs">
                        <Icon name="lock" /> Read-only
                      </span>
                    </div>

                    <div className="transcript-messages">
                      {activeConversation.messages.map((msg, i) => (
                        <div
                          key={i}
                          className={`transcript-bubble ${msg.role === 'user' ? 'student' : 'assistant'}`}
                        >
                          <div className="bubble-meta">
                            <span className="author-name">
                              {msg.role === 'user' ? 'Bạn (Học sinh)' : 'Trợ lý Lumi'}
                            </span>
                            <span className="msg-time">{msg.timestamp}</span>
                          </div>
                          <div className="bubble-content">{msg.content}</div>
                        </div>
                      ))}
                    </div>

                    <div className="viewer-footer muted text-xs">
                      🔒 Phiên hỏi đáp đã được lưu trữ an toàn. Không thể gửi thêm tin nhắn vào lịch sử này.
                    </div>
                  </>
                ) : (
                  <p className="muted padded">Chọn một hội thoại để xem lại nội dung.</p>
                )}
              </div>
            </div>
          )}
        </section>

        {/* Right: Saved Class Notes */}
        <section className="history-section history-notes-section">
          <div className="section-header">
            <div>
              <h3>Ghi chú cá nhân ({notes.length})</h3>
              <p className="muted text-sm">Các ghi chú bạn đã lưu trong môn học này</p>
            </div>
          </div>

          {notes.length === 0 ? (
            <div className="card empty-card">
              <p className="muted">Không có ghi chú nào được lưu cho lớp này.</p>
            </div>
          ) : (
            <div className="notes-list">
              {notes.map(note => (
                <article key={note.id} className="card note-item-card">
                  <div className="note-item-header">
                    <h4>{note.title}</h4>
                    <span className="muted text-xs">{note.date}</span>
                  </div>
                  <p className="note-content text-sm">{note.content}</p>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
