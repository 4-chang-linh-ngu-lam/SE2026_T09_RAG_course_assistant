'use client';
import { useState, useTransition, useEffect, useRef } from 'react';
import Link from 'next/link';
import type { RouteDefinition } from '@/config/routes';
import type { CitationItem, PersonalNoteItem, RouteParams, StudentTutorWorkspaceData, TutorConversation, TutorMessage, TutorMode, WorkspaceData } from '@/lib/domain';
import { adapter } from '@/lib/data';
import { draftStore, getTutorDraft, setTutorDraft } from '@/lib/draft-store';
import { useSession } from '@/components/session-provider';
import { StatePanel, Icon, Dialog } from '@/components/ui';
import '../tutor.css';
import { stopTutorStream } from '../stop-stream';
import { errorMessage } from '@/lib/api/errors';

type Props = {
  route: RouteDefinition;
  data: WorkspaceData | null;
  params: RouteParams;
  reload(): void;
};

export function StudentTutorWorkspace({ data, params, reload }: Props) {
  const { user } = useSession();
  const userId = user?.id ?? 'anon';
  const [selectedConvId, setSelectedConvId] = useState<string | null>(null);
  const [mode, setMode] = useState<TutorMode>(() => {
    return params.mode === 'QUICK_QA' ? 'QUICK_QA' : 'STEP_BY_STEP';
  });
  const [inputContent, setInputContent] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [isDrawerHistoryOpen, setIsDrawerHistoryOpen] = useState(false);
  const [isDrawerCitationsOpen, setIsDrawerCitationsOpen] = useState(false);
  const [isPending, startTransition] = useTransition();

  const activeStreamRef = useRef<{
    classId: string;
    convId: string;
    generation: number;
    controller: AbortController;
  } | null>(null);
  const generationRef = useRef(0);

  const tutorData: StudentTutorWorkspaceData | undefined = data?.kind === 'ready' ? data.tutorWorkspace : undefined;
  const activeClassId = params.classId ?? tutorData?.classSummary.id ?? '';
  const identityRef = useRef('');
  identityRef.current = JSON.stringify([userId, activeClassId, selectedConvId]);

  // Synchronize initial active conversation with safe URL conversationId
  const explicitUnknownId = Boolean(
    params.conversationId &&
    tutorData?.conversations &&
    !tutorData.conversations.some(c => c.id === params.conversationId)
  );

  useEffect(() => {
    if (params.compose === 'new') {
      setSelectedConvId(null);
      return;
    }
    if (tutorData?.conversations) {
      if (params.conversationId) {
        // Unknown explicit conversation IDs never fallback to first
        setSelectedConvId(params.conversationId);
      } else if (!selectedConvId && tutorData.conversations.length > 0) {
        setSelectedConvId(tutorData.activeConversationId ?? tutorData.conversations[0].id);
      }
    }
  }, [tutorData, selectedConvId, params.conversationId, params.compose]);

  // Handle switching conversations with its own draft or empty, no carry-over
  const handleSelectConv = (convId: string) => {
    if (selectedConvId === convId) return;
    generationRef.current++;
    if (activeStreamRef.current && activeStreamRef.current.convId !== convId) {
      activeStreamRef.current.controller.abort();
      activeStreamRef.current = null;
      setIsStreaming(false);
      setStreamingContent(null);
    }
    setSelectedConvId(convId);
    if (typeof window !== 'undefined') {
      const url = new URL(window.location.href);
      url.searchParams.delete('compose');
      url.searchParams.set('conversationId', convId);
      window.history.replaceState(null, '', url.toString());
    }
    if (activeClassId) {
      const saved = getTutorDraft(userId, activeClassId, convId);
      setInputContent(saved ?? '');
    } else {
      setInputContent('');
    }
  };

  // Restore draft when activeClassId, selectedConvId, or userId changes
  useEffect(() => {
    if (activeClassId) {
      const convId = selectedConvId ?? 'new';
      const saved = getTutorDraft(userId, activeClassId, convId);
      setInputContent(saved ?? '');
    }
  }, [activeClassId, selectedConvId, userId]);

  // Persist input to draftStore on change
  const handleInputChange = (val: string) => {
    setInputContent(val);
    if (activeClassId) {
      setTutorDraft(userId, activeClassId, val, selectedConvId ?? 'new');
    }
  };

  useEffect(() => {
    if (tutorData?.isOfficialAssessmentActive && activeStreamRef.current) {
      generationRef.current++;
      activeStreamRef.current.controller.abort();
      activeStreamRef.current = null;
      setIsStreaming(false);
      setStreamingContent(null);
    }
  }, [tutorData?.isOfficialAssessmentActive]);

  // Native Back/Forward and URL changes also invalidate the previous stream.
  useEffect(() => {
    const stream = activeStreamRef.current;
    if (stream && (stream.classId !== activeClassId || (stream.convId && stream.convId !== selectedConvId))) {
      generationRef.current++; stream.controller.abort(); activeStreamRef.current = null;
      setIsStreaming(false); setStreamingContent(null);
    }
  }, [userId, activeClassId, selectedConvId]);

  // Cancel in-flight stream on unmount only
  useEffect(() => {
    return () => {
      generationRef.current++;
      if (activeStreamRef.current) {
        activeStreamRef.current.controller.abort();
        activeStreamRef.current = null;
      }
    };
  }, []);

  if (!data) {
    return <StatePanel busy title="Đang tải không gian Trợ lý AI Lumi…" />;
  }

  if (data.kind === 'unavailable') {
    return (
      <StatePanel title="Trợ lý AI chưa sẵn sàng" message={data.message}>
        <button type="button" className="button" onClick={reload}>
          Thử lại
        </button>
      </StatePanel>
    );
  }

  if (data.kind === 'empty' || !tutorData) {
    return <StatePanel title="Không có dữ liệu trợ lý" message={data.kind === 'empty' ? data.message : 'Dữ liệu trợ lý không khả dụng.'} />;
  }

  const conversations: TutorConversation[] = tutorData.conversations ?? [];
  const activeConv: TutorConversation | undefined = conversations.find(c => c.id === selectedConvId);
  const isAssessmentLocked = tutorData.isOfficialAssessmentActive;
  const hasSources = tutorData.classHasSources;

  // Derive citations from current assistant message or default
  const lastAssistantMsg = activeConv?.messages.filter(m => m.role === 'assistant').slice(-1)[0];
  const activeCitations: CitationItem[] = lastAssistantMsg?.citations ?? [];

  const handleOpenNewCompose = () => {
    if (isAssessmentLocked || !activeClassId) return;
    generationRef.current++;
    if (activeStreamRef.current) {
      activeStreamRef.current.controller.abort();
      activeStreamRef.current = null;
      setIsStreaming(false);
      setStreamingContent(null);
    }
    setSelectedConvId(null);
    if (typeof window !== 'undefined') {
      const url = new URL(window.location.href);
      url.searchParams.delete('conversationId');
      url.searchParams.set('compose', 'new');
      window.history.pushState(null, '', url.toString());
    }
    const saved = getTutorDraft(userId, activeClassId, 'new');
    setInputContent(saved ?? '');
  };

  const handleSendMessage = async (e?: React.FormEvent, retryText?: string, isRetryMode?: boolean, retryUserMessageId?: string) => {
    if (e) e.preventDefault();
    const contentToSend = (retryText ?? inputContent).trim();
    if (!contentToSend || isAssessmentLocked || !activeClassId) return;
    if (isStreaming || activeStreamRef.current) return;
    if (explicitUnknownId) {
      setActionError('Không thể gửi câu hỏi vào cuộc trò chuyện không tồn tại hoặc không có quyền truy cập.');
      return;
    }

    setActionError(null);
    setIsStreaming(true);
    setStreamingContent('');

    const generation = ++generationRef.current;
    const controller = new AbortController();
    activeStreamRef.current = {classId: activeClassId, convId: selectedConvId ?? '', generation, controller};

    try {
      let targetConvId = selectedConvId;
      // Tutor start with no conversation must create one then send
      if (!targetConvId || !activeConv) {
        const created = await adapter.tutor.createConversation(activeClassId, contentToSend.slice(0, 30));
        if (controller.signal.aborted || generationRef.current !== generation) return;
        targetConvId = created.id;
        setSelectedConvId(created.id);
        if (typeof window !== 'undefined') {
          const url = new URL(window.location.href);
          url.searchParams.delete('compose');
          url.searchParams.set('conversationId', created.id);
          window.history.replaceState(null, '', url.toString());
        }
      }

      activeStreamRef.current = {
        classId: activeClassId,
        convId: targetConvId,
        generation,
        controller,
      };

      await adapter.tutor.sendMessage({
        conversationId: targetConvId,
        classId: activeClassId,
        content: contentToSend,
        mode,
        isRetry: isRetryMode,
        retryUserMessageId,
        onChunk: (chunk: string) => {
          if (activeStreamRef.current?.generation === generation) {
            setStreamingContent(chunk);
          }
        },
        signal: controller.signal,
      });

      // Clear draft after successful transmission
      if (activeStreamRef.current?.generation === generation) {
        setInputContent('');
        draftStore.remove(`tutor:${userId}:${activeClassId}:${targetConvId}`);
        draftStore.remove(`tutor:${userId}:${activeClassId}:new`);
        reload();
      }
    } catch (err) {
      if (!controller.signal.aborted && generationRef.current === generation) {
        setActionError(err instanceof Error ? err.message : 'Không thể gửi câu hỏi đến trợ lý.');
      }
    } finally {
      if (activeStreamRef.current?.generation === generation) {
        activeStreamRef.current = null;
        setIsStreaming(false);
        setStreamingContent(null);
      }
    }
  };

  const handleStopStreaming = async () => {
    const stream = activeStreamRef.current;
    const identity = identityRef.current;
    const generation = ++generationRef.current;
    const result = await stopTutorStream({
      conversationId: stream?.convId || selectedConvId,
      stopLocally() {
        stream?.controller.abort();
        if (activeStreamRef.current === stream) activeStreamRef.current = null;
        setIsStreaming(false); setStreamingContent(null);
      },
      stopRemote: conversationId => adapter.tutor.stopStreaming(conversationId),
      isCurrent: () => generationRef.current === generation && identityRef.current === identity,
    });
    if (result.kind === 'confirmed') reload();
    else if (result.kind === 'unconfirmed') setActionError(errorMessage(result.error));
  };

  return (
    <div className="tutor-workspace-root">
      {/* Top Mobile Bar */}
      <div className="tutor-mobile-controls"><button type="button" className="button small secondary tutor-new-mobile" aria-label="Tạo cuộc trò chuyện mới" onClick={handleOpenNewCompose} disabled={isAssessmentLocked || isStreaming}><Icon name="plus"/>Cuộc trò chuyện mới</button>
        <button
          type="button"
          className="button small secondary tutor-history-toggle"
          onClick={() => setIsDrawerHistoryOpen(true)}
        >
          <Icon name="chat" />
          <span>Lịch sử ({conversations.length})</span>
        </button>
        <button
          type="button"
          className="button small secondary"
          onClick={() => setIsDrawerCitationsOpen(true)}
        >
          <Icon name="book" />
          <span>Căn cứ ({activeCitations.length})</span>
        </button>
      </div>

      <div className="tutor-workspace-grid">
        {/* Left Column: Conversation History */}
        <aside className="tutor-history-col card">
          <div className="history-col-header">
            <h3>Lịch sử hỏi đáp</h3>
            <button
              id="ux-new-conversation-btn"
              type="button"
              className="button small primary"
              onClick={handleOpenNewCompose}
              disabled={isAssessmentLocked || isPending}
              aria-label="Tạo cuộc trò chuyện mới"
            >
              <Icon name="plus" />
              <span>Mới</span>
            </button>
          </div>

          <nav className="history-conv-list" aria-label="Danh sách cuộc trò chuyện">
            {conversations.length === 0 ? (
              <p className="muted text-xs p-4 text-center">Chưa có cuộc trò chuyện nào.</p>
            ) : (
              conversations.map(conv => (
                <button
                  key={conv.id}
                  type="button"
                  data-conv-id={conv.id}
                  className={`history-conv-item ${selectedConvId === conv.id ? 'active' : ''}`}
                  onClick={() => handleSelectConv(conv.id)}
                >
                  <div className="conv-item-top">
                    <strong className="conv-title">{conv.title}</strong>
                    <span className="text-xs muted">{conv.updatedAt}</span>
                  </div>
                  <p className="conv-preview text-xs muted line-clamp-1">{conv.preview}</p>
                </button>
              ))
            )}
          </nav>
        </aside>

        {/* Center Column: Transcript & Composer */}
        <section className="tutor-chat-col card" tabIndex={0} aria-label="Khu vực trò chuyện với Lumi">
          {/* AI05: Official Assessment Lock State (Rule D6) */}
          {isAssessmentLocked && (
            <div className="tutor-lock-banner card p-4 mb-4" role="alert">
              <div className="lock-banner-header">
                <Icon name="lock" />
                <strong>Khóa tương tác AI trong giờ kiểm tra chính thức</strong>
              </div>
              <p className="text-xs mt-1">
                Bạn đang có lượt kiểm tra chính thức chưa kết thúc ({tutorData.assessmentTitle ?? 'Đang diễn ra'}). Hỏi Lumi tích hợp tạm tắt cho đến khi hệ thống xác nhận lượt làm đã kết thúc.
              </p>
              {tutorData.assessmentHref && (
                <Link href={tutorData.assessmentHref} className="button small primary mt-2 inline-flex">
                  Đến bài kiểm tra
                </Link>
              )}
            </div>
          )}

          {/* AI01: No Sources Grounding Banner */}
          {!hasSources && !isAssessmentLocked && (
            <div className="notice-box info mb-3">
              <Icon name="info" />
              <span>Lớp học chưa có tài liệu chia sẻ. Trợ lý Lumi sẽ giải đáp dựa trên kiến thức phổ thông chung.</span>
            </div>
          )}

          {actionError && <p className="notice error mb-3" role="alert">{actionError}</p>}

          {/* Messages Transcript */}
          <div className="tutor-messages-stream">
            {explicitUnknownId ? (
              <div className="tutor-unknown-splash card p-6 text-center" role="alert">
                <div className="tutor-state-icon"><Icon name="lock"/></div>
                <h3 className="font-semibold text-base mb-1">Cuộc trò chuyện không tồn tại hoặc không có quyền truy cập</h3>
                <p className="muted text-sm mb-4">
                  Mã cuộc trò chuyện ({selectedConvId}) không thuộc quyền sở hữu của bạn hoặc đã bị xóa. Vui lòng chọn một cuộc trò chuyện từ danh sách hoặc bắt đầu cuộc trò chuyện mới.
                </p>
                <button
                  type="button"
                  className="button secondary small"
                  onClick={() => {
                    setSelectedConvId(null);
                    if (typeof window !== 'undefined') {
                      const url = new URL(window.location.href);
                      url.searchParams.delete('conversationId');
                      window.history.replaceState(null, '', url.toString());
                    }
                  }}
                >
                  Bỏ chọn mã trò chuyện này
                </button>
              </div>
            ) : !activeConv || activeConv.messages.length === 0 ? (
              <div className="tutor-empty-splash">
                <div className="tutor-sparkle-icon"><Icon name="sparkles"/></div>
                <h3>Chào bạn, mình là Lumi!</h3>
                <p className="muted text-sm">
                  Hãy nhập câu hỏi bên dưới để được hướng dẫn phương pháp giải từng bước dựa trên tài liệu bài học của lớp.
                </p>
              </div>
            ) : (
              activeConv.messages.map((msg, messageIndex) => {
                const isAssistant = msg.role === 'assistant';
                return (
                  <div
                    key={msg.id}
                    className={`tutor-msg-wrapper ${isAssistant ? 'assistant' : 'student'}`}
                  >
                    <div className="msg-header">
                      <strong>{isAssistant ? 'Trợ lý Lumi' : 'Bạn'}</strong>
                      <span className="text-xs muted">{msg.timestamp}</span>
                    </div>

                    <div className="msg-bubble">
                      {isAssistant && msg.stepNumber && (
                        <div className="step-badge">
                          Bước {msg.stepNumber} {msg.totalSteps ? ` / ${msg.totalSteps}` : ''}
                        </div>
                      )}

                      <div className="msg-content-text">{msg.content}</div>

                      {/* AI04 Incomplete stopped indicator */}
                      {msg.isIncomplete && (
                        <div className="incomplete-indicator text-xs muted mt-2">
                          (Đã dừng phản hồi theo yêu cầu của học sinh)
                        </div>
                      )}

                      {/* Pedagogical Hint */}
                      {msg.pedagogicalHint && (
                        <div className="pedagogical-hint-box">
                          <Icon name="book" />
                          <span>{msg.pedagogicalHint}</span>
                        </div>
                      )}

                      {/* AI03: Retry failed message button */}
                      {msg.isFailed && (
                        <div className="failed-retry-row mt-2">
                          <span className="text-xs text-red-600">Gặp lỗi trong quá trình xử lý câu hỏi.</span>
                          <button
                            type="button"
                            className="button small secondary"
                            onClick={() => { const previous = activeConv.messages.slice(0, messageIndex).reverse().find(m => m.role === 'user'); if (previous) void handleSendMessage(undefined, previous.content, true, previous.id); }}
                            disabled={isStreaming || isAssessmentLocked}
                          >
                            Thử lại câu hỏi
                          </button>
                        </div>
                      )}

                      {/* Citations badges within bubble */}
                      {msg.citations && msg.citations.length > 0 && (
                        <div className="msg-citations-row mt-3">
                          <span className="text-xs muted mr-2">Căn cứ trích dẫn:</span>
                          {msg.citations.map(c => {
                            if (!c.isAccessible) {
                              return (
                                <span
                                  key={c.id}
                                  className="citation-pill-link citation-pill-inaccessible"
                                  title="Tài liệu trích dẫn không còn khả dụng hoặc đã bị thu hồi"
                                >
                                  <Icon name="file" />
                                  <span>{c.documentTitle} ({c.locator}) [Không khả dụng]</span>
                                </span>
                              );
                            }
                            return (
                              <Link
                                key={c.id}
                                href={c.readerHref}
                                className="citation-pill-link"
                                title={c.excerpt}
                              >
                                <Icon name="file" />
                                <span>{c.documentTitle} ({c.locator})</span>
                              </Link>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })
            )}

            {/* Live Streaming Bubble */}
            {isStreaming && (
              <div className="tutor-msg-wrapper assistant streaming">
                <div className="msg-header">
                  <strong>Trợ lý Lumi</strong>
                  <span className="badge info text-xs animate-pulse">Đang giải đáp…</span>
                </div>
                <div className="msg-bubble">
                  <div className="msg-content-text">{streamingContent || 'Đang tra cứu tài liệu học tập của lớp…'}</div>
                </div>
              </div>
            )}
          </div>

          {/* Chat Composer */}
          <footer className="tutor-composer-area">
            {/* Mode selector */}
            <div className="composer-mode-bar">
              <span className="text-xs muted mr-2">Chế độ giải đáp:</span>
              <button
                type="button"
                className={`tag cursor-pointer ${mode === 'STEP_BY_STEP' ? 'primary' : 'default'}`}
                onClick={() => setMode('STEP_BY_STEP')}
                disabled={isAssessmentLocked || isStreaming || explicitUnknownId}
              >
                Gợi ý từng bước
              </button>
              <button
                type="button"
                className={`tag cursor-pointer ${mode === 'QUICK_QA' ? 'primary' : 'default'}`}
                onClick={() => setMode('QUICK_QA')}
                disabled={isAssessmentLocked || isStreaming || explicitUnknownId}
              >
                Hỏi đáp nhanh
              </button>

              {/* AI04: Stop Streaming Button */}
              {isStreaming && (
                <button
                  id="ux-stop-streaming-btn"
                  type="button"
                  className="button small danger ml-auto"
                  onClick={handleStopStreaming}
                >
                  <Icon name="stop" />
                  <span>Dừng tạo câu trả lời</span>
                </button>
              )}
            </div>

            <form onSubmit={handleSendMessage} className="composer-form">
              <label htmlFor="tutorMessageTextarea" className="sr-only">Nội dung câu hỏi học tập</label>
              <textarea
                id="tutorMessageTextarea"
                className="input composer-textarea"
                placeholder={
                  explicitUnknownId
                    ? 'Cuộc trò chuyện không tồn tại hoặc bạn không có quyền truy cập.'
                    : isAssessmentLocked
                    ? 'Chức năng trợ lý tạm khóa trong thời gian diễn ra bài kiểm tra.'
                    : 'Đặt câu hỏi về bài học, công thức hoặc bài tập…'
                }
                rows={3}
                value={inputContent}
                onChange={e => handleInputChange(e.target.value)}
                disabled={isAssessmentLocked || isStreaming || explicitUnknownId}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    void handleSendMessage();
                  }
                }}
              />
              <div className="composer-action-bar">
                <span className="text-xs muted">Nhấn Enter để gửi, Shift+Enter để xuống dòng</span>
                <button
                  id="ux-send-message-btn"
                  type="submit"
                  className="button primary"
                  disabled={isAssessmentLocked || isStreaming || !inputContent.trim() || explicitUnknownId}
                >
                  <Icon name="send" />
                  <span>Gửi câu hỏi</span>
                </button>
              </div>
            </form>
          </footer>
        </section>

        {/* Right Column: Citations & Quick Notes */}
        <aside className="tutor-citations-col card">
          <div className="citations-section-header">
            <Icon name="book" />
            <h3>Căn cứ tài liệu</h3>
          </div>

          <Link className="button tutor-documents-link" href={`/student/classes/${activeClassId}/documents`}><Icon name="folder"/>Xem tài liệu lớp</Link>
          <div className="citations-list">
            {activeCitations.length === 0 ? (
              <p className="muted text-xs p-3">Chưa có trích dẫn tài liệu cụ thể trong đoạn hội thoại này.</p>
            ) : (
              activeCitations.map(cite => (
                <div key={cite.id} className="citation-card card p-3 mb-2">
                  <div className="citation-card-top">
                    <span className={`badge ${cite.isAccessible ? 'primary' : 'secondary'} text-xs`}>
                      {cite.isAccessible ? 'Trích dẫn' : 'Trích dẫn cũ'}
                    </span>
                    <span className="text-xs font-semibold">{cite.locator}</span>
                  </div>
                  <strong className="citation-doc-name text-xs block mt-1">{cite.documentTitle}</strong>
                  {cite.isAccessible ? (
                    <>
                      <blockquote className="citation-quote text-xs muted mt-1">
                        “{cite.excerpt}”
                      </blockquote>
                      <Link href={cite.readerHref} className="link-button text-xs mt-2 block">
                        Mở tài liệu đúng vị trí →
                      </Link>
                    </>
                  ) : (
                    <p className="text-xs muted italic mt-1">
                      Tài liệu gốc đã bị thu hồi hoặc bạn không còn quyền truy cập.
                    </p>
                  )}
                </div>
              ))
            )}
          </div>

          <div className="quick-notes-section-header mt-4 pt-3 border-t">
            <Icon name="edit" />
            <h3>Ghi chú bài học</h3>
          </div>

          <div className="quick-notes-list">
            {tutorData.quickNotes.length === 0 ? (
              <p className="muted text-xs p-3">Chưa có ghi chú nào trong lớp này.</p>
            ) : (
              tutorData.quickNotes.map(n => (
                <div key={n.id} className="quick-note-item card p-2 mb-2">
                  <span className="badge info text-xs">{n.locator}</span>
                  <p className="text-xs mt-1 line-clamp-2">{n.noteText}</p>
                </div>
              ))
            )}
          </div>
        </aside>
      </div>

      {/* Mobile Drawer: Conversation History */}
      <Dialog
        open={isDrawerHistoryOpen}
        title="Lịch sử hỏi đáp"
        onClose={() => setIsDrawerHistoryOpen(false)}
      >
        <div className="mobile-history-list"><button type="button" className="button primary" disabled={isAssessmentLocked || isStreaming} onClick={() => {handleOpenNewCompose(); setIsDrawerHistoryOpen(false);}}><Icon name="plus"/>Cuộc trò chuyện mới</button>
          {conversations.map(conv => (
            <button
              key={conv.id}
              type="button"
              className={`history-conv-item ${selectedConvId === conv.id ? 'active' : ''}`}
              onClick={() => {
                handleSelectConv(conv.id);
                setIsDrawerHistoryOpen(false);
              }}
            >
              <strong>{conv.title}</strong>
              <p className="text-xs muted">{conv.preview}</p>
            </button>
          ))}
        </div>
      </Dialog>

      {/* Mobile Drawer: Citations & Notes */}
      <Dialog
        open={isDrawerCitationsOpen}
        title="Căn cứ & Ghi chú"
        onClose={() => setIsDrawerCitationsOpen(false)}
      >
        <div className="mobile-citations-list"><Link className="button tutor-documents-link" href={`/student/classes/${activeClassId}/documents`}><Icon name="folder"/>Xem tài liệu lớp</Link>{activeCitations.length === 0 && <p className="muted">Chưa có trích dẫn trong câu trả lời này.</p>}
          {activeCitations.map(cite => (
            <div key={cite.id} className="citation-card card p-3 mb-2">
              <strong>{cite.documentTitle} ({cite.locator})</strong>
              {cite.isAccessible ? (
                <>
                  <p className="text-xs muted mt-1">“{cite.excerpt}”</p>
                  <Link href={cite.readerHref} className="link-button text-xs mt-1 block">
                    Mở tài liệu đúng vị trí
                  </Link>
                </>
              ) : (
                <p className="text-xs muted italic mt-1">Tài liệu không còn khả dụng.</p>
              )}
            </div>
          ))}
        <section className="mobile-quick-notes"><h3>Ghi chú bài học</h3>{tutorData.quickNotes.length === 0 ? <p className="muted">Chưa có ghi chú trong lớp này.</p> : tutorData.quickNotes.map(note => <article className="quick-note-item card" key={note.id}><span className="note-locator-badge">{note.locator}</span><p>{note.noteText}</p></article>)}</section></div>
      </Dialog>
    </div>
  );
}
