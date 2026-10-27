'use client';
import { useId, type ChangeEvent } from 'react';
import Link from 'next/link';
import type {
  PracticeQuestion,
  PracticeAnswer,
  PracticeQuestionFeedback,
  SingleChoiceQuestion,
  MultipleChoiceQuestion,
  TrueFalseQuestion,
  ShortAnswerQuestion,
} from '@/lib/domain';

type Props = {
  question: PracticeQuestion;
  questionNumber: number;
  answer?: PracticeAnswer;
  onAnswerChange?: (answer: PracticeAnswer) => void;
  feedback?: PracticeQuestionFeedback;
  readOnly?: boolean;
  classId?: string;
};

export function QuestionRenderer({
  question,
  questionNumber,
  answer,
  onAnswerChange,
  feedback,
  readOnly = false,
  classId,
}: Props) {
  const uniqueId = useId();
  const singleChoiceName = `sc_${question.id}_${uniqueId}`;
  const shortAnswerId = `sa_${question.id}_${uniqueId}`;

  const handleSingleChoice = (optionId: string) => {
    if (readOnly || !onAnswerChange) return;
    onAnswerChange({
      questionId: question.id,
      singleChoiceValue: optionId,
    });
  };

  const handleMultipleChoice = (optionId: string) => {
    if (readOnly || !onAnswerChange) return;
    const current = answer?.multipleChoiceValues ?? [];
    const updated = current.includes(optionId)
      ? current.filter(id => id !== optionId)
      : [...current, optionId];
    onAnswerChange({
      questionId: question.id,
      multipleChoiceValues: updated,
    });
  };

  const handleTrueFalse = (statementId: string, value: boolean) => {
    if (readOnly || !onAnswerChange) return;
    const current = answer?.trueFalseValues ?? {};
    onAnswerChange({
      questionId: question.id,
      trueFalseValues: {
        ...current,
        [statementId]: value,
      },
    });
  };

  const handleShortAnswer = (e: ChangeEvent<HTMLInputElement>) => {
    if (readOnly || !onAnswerChange) return;
    onAnswerChange({
      questionId: question.id,
      shortAnswerValue: e.target.value,
    });
  };

  const renderSourceLink = (sourceRef: NonNullable<PracticeQuestion['sourceRef']>, isFeedback = false) => {
    const isAccessible = sourceRef.isAccessible !== false;
    const displayText = sourceRef.displayText || sourceRef.locator || sourceRef.documentTitle;

    if (!isAccessible) {
      return (
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            fontSize: '12px',
            color: '#64748B',
            backgroundColor: '#F1F5F9',
            padding: '4px 10px',
            borderRadius: '6px',
          }}
        >
          <span>{isFeedback ? 'Trích dẫn' : 'Nguồn'}: Tài liệu không còn khả dụng</span>
        </span>
      );
    }

    const docHref = classId
      ? `/student/classes/${classId}/documents/${sourceRef.documentId}?version=${sourceRef.versionNumber}&page=${sourceRef.pageNumber ?? 1}`
      : `/student/documents/${sourceRef.documentId}?version=${sourceRef.versionNumber}&page=${sourceRef.pageNumber ?? 1}`;

    return (
      <Link
        href={docHref}
        className="source-reference-link"
        target="_blank"
        rel="noopener noreferrer"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '6px',
          fontSize: '12px',
          color: '#2563EB',
          backgroundColor: '#EFF6FF',
          padding: '4px 10px',
          borderRadius: '6px',
          textDecoration: 'none',
          fontWeight: 500,
        }}
        data-testid={isFeedback ? 'feedback-source-ref-link' : 'question-source-ref-link'}
      >
        <span aria-hidden="true">📖</span>
        <span>{isFeedback ? 'Trích dẫn' : 'Nguồn'}: {displayText}</span>
      </Link>
    );
  };

  return (
    <div
      className="card question-card"
      style={{
        padding: '24px',
        marginBottom: '24px',
        backgroundColor: '#fff',
        borderRadius: '12px',
        border: '1px solid #E2E8F0',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '16px',
          flexWrap: 'wrap',
          gap: '8px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              minWidth: '32px',
              height: '32px',
              padding: '0 8px',
              borderRadius: '8px',
              backgroundColor: '#EFF6FF',
              color: '#2563EB',
              fontWeight: 700,
              fontSize: '13px',
            }}
          >
            Câu {questionNumber}
          </span>
          {question.topic && (
            <span style={{ fontSize: '13px', color: '#64748B', fontWeight: 500 }}>
              {question.topic}
            </span>
          )}
        </div>
        {typeof question.points === 'number' && (
          <span
            style={{
              fontSize: '12px',
              fontWeight: 600,
              padding: '2px 8px',
              borderRadius: '6px',
              backgroundColor: '#F1F5F9',
              color: '#475569',
            }}
          >
            {question.points} điểm
          </span>
        )}
      </div>

      <div
        style={{
          fontSize: '15px',
          lineHeight: 1.6,
          fontWeight: 600,
          color: '#0F172A',
          marginBottom: '16px',
        }}
      >
        {question.prompt}
      </div>

      {question.sourceRef && (
        <div style={{ marginBottom: '16px' }}>
          {renderSourceLink(question.sourceRef, false)}
        </div>
      )}

      {/* Single Choice Form */}
      {question.type === 'single_choice' && (
        <div
          style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}
          role="radiogroup"
          aria-label={`Các lựa chọn cho câu ${questionNumber}`}
        >
          {(question as SingleChoiceQuestion).options.map(opt => {
            const isSelected = answer?.singleChoiceValue === opt.id;
            const inputId = `opt_${question.id}_${opt.id}_${uniqueId}`;
            return (
              <label
                key={opt.id}
                htmlFor={inputId}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '12px',
                  padding: '12px 16px',
                  borderRadius: '10px',
                  border: isSelected ? '2px solid #2563EB' : '1px solid #E2E8F0',
                  backgroundColor: isSelected ? '#EFF6FF' : '#FFFFFF',
                  cursor: readOnly ? 'default' : 'pointer',
                  transition: 'border-color 0.15s, background-color 0.15s',
                }}
              >
                <input
                  id={inputId}
                  type="radio"
                  name={singleChoiceName}
                  value={opt.id}
                  checked={isSelected}
                  disabled={readOnly}
                  onChange={() => handleSingleChoice(opt.id)}
                  style={{ accentColor: '#2563EB', cursor: readOnly ? 'default' : 'pointer' }}
                />
                <span style={{ fontWeight: 700, color: '#0F172A', minWidth: '22px' }}>{opt.label}.</span>
                <span style={{ flex: 1, fontSize: '14px', color: '#1E293B' }}>{opt.text}</span>
              </label>
            );
          })}
        </div>
      )}

      {/* Multiple Choice Form */}
      {question.type === 'multiple_choice' && (
        <div
          style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}
          role="group"
          aria-label={`Các phương án lựa chọn cho câu ${questionNumber}`}
        >
          {(question as MultipleChoiceQuestion).options.map(opt => {
            const isChecked = (answer?.multipleChoiceValues ?? []).includes(opt.id);
            const inputId = `mc_${question.id}_${opt.id}_${uniqueId}`;
            return (
              <label
                key={opt.id}
                htmlFor={inputId}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '12px',
                  padding: '12px 16px',
                  borderRadius: '10px',
                  border: isChecked ? '2px solid #2563EB' : '1px solid #E2E8F0',
                  backgroundColor: isChecked ? '#EFF6FF' : '#FFFFFF',
                  cursor: readOnly ? 'default' : 'pointer',
                  transition: 'border-color 0.15s, background-color 0.15s',
                }}
              >
                <input
                  id={inputId}
                  type="checkbox"
                  name={`mc_${question.id}_${uniqueId}`}
                  value={opt.id}
                  checked={isChecked}
                  disabled={readOnly}
                  onChange={() => handleMultipleChoice(opt.id)}
                  style={{ accentColor: '#2563EB', cursor: readOnly ? 'default' : 'pointer' }}
                />
                <span style={{ fontWeight: 700, color: '#0F172A', minWidth: '22px' }}>{opt.label}.</span>
                <span style={{ flex: 1, fontSize: '14px', color: '#1E293B' }}>{opt.text}</span>
              </label>
            );
          })}
        </div>
      )}

      {/* True/False Form */}
      {question.type === 'true_false' && (
        <div
          className="table-scroll"
          style={{
            border: '1px solid #E2E8F0',
            borderRadius: '10px',
            overflowX: 'auto',
            maxWidth: '100%',
          }}
        >
          <table style={{ width: '100%', minWidth: '320px', borderCollapse: 'collapse', textAlign: 'left', fontSize: '13px' }}>
            <thead>
              <tr style={{ backgroundColor: '#F8FAFC', borderBottom: '1px solid #E2E8F0', color: '#475569' }}>
                <th style={{ padding: '12px 16px', fontWeight: 600 }}>Mệnh đề</th>
                <th style={{ padding: '12px 16px', width: '88px', textAlign: 'center', fontWeight: 600 }}>
                  Đúng
                </th>
                <th style={{ padding: '12px 16px', width: '88px', textAlign: 'center', fontWeight: 600 }}>
                  Sai
                </th>
              </tr>
            </thead>
            <tbody>
              {(question as TrueFalseQuestion).statements.map(stmt => {
                const currentVal = answer?.trueFalseValues?.[stmt.id];
                const stmtRadioName = `tf_${question.id}_${stmt.id}_${uniqueId}`;
                return (
                  <tr key={stmt.id} style={{ borderBottom: '1px solid #F1F5F9' }}>
                    <td style={{ padding: '12px 16px', color: '#1E293B' }}>
                      <strong style={{ marginRight: '6px', color: '#0F172A' }}>{stmt.label})</strong>
                      <span>{stmt.text}</span>
                    </td>
                    <td style={{ padding: '12px 16px', textAlign: 'center' }}>
                      <input
                        type="radio"
                        name={stmtRadioName}
                        value="true"
                        checked={currentVal === true}
                        disabled={readOnly}
                        aria-label={`Mệnh đề ${stmt.label}: ${stmt.text} — Chọn Đúng`}
                        onChange={() => handleTrueFalse(stmt.id, true)}
                        style={{ cursor: readOnly ? 'default' : 'pointer', accentColor: '#2563EB' }}
                      />
                    </td>
                    <td style={{ padding: '12px 16px', textAlign: 'center' }}>
                      <input
                        type="radio"
                        name={stmtRadioName}
                        value="false"
                        checked={currentVal === false}
                        disabled={readOnly}
                        aria-label={`Mệnh đề ${stmt.label}: ${stmt.text} — Chọn Sai`}
                        onChange={() => handleTrueFalse(stmt.id, false)}
                        style={{ cursor: readOnly ? 'default' : 'pointer', accentColor: '#2563EB' }}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Short Answer Form */}
      {question.type === 'short_answer' && (
        <div style={{ marginTop: '12px' }}>
          <label
            htmlFor={shortAnswerId}
            style={{ display: 'block', fontSize: '13px', fontWeight: 600, color: '#334155', marginBottom: '8px' }}
          >
            Nhập câu trả lời ngắn:
          </label>
          <input
            id={shortAnswerId}
            type="text"
            className="input"
            placeholder="Nhập câu trả lời của bạn..."
            value={answer?.shortAnswerValue ?? ''}
            disabled={readOnly}
            onChange={handleShortAnswer}
            style={{
              maxWidth: '360px',
              width: '100%',
              fontSize: '14px',
              padding: '10px 14px',
              borderRadius: '8px',
              border: '1px solid #CBD5E1',
            }}
          />
        </div>
      )}

      {/* Immediate Feedback Card */}
      {feedback && (
        <div
          data-testid="feedback-card"
          style={{
            marginTop: '20px',
            padding: '16px',
            borderRadius: '10px',
            backgroundColor: feedback.isCorrect ? '#F0FDF4' : '#FEF2F2',
            border: `1px solid ${feedback.isCorrect ? '#86EFAC' : '#FECACA'}`,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                width: '24px',
                height: '24px',
                borderRadius: '50%',
                backgroundColor: feedback.isCorrect ? '#16A34A' : '#DC2626',
                color: '#fff',
                fontSize: '13px',
                fontWeight: 700,
              }}
            >
              {feedback.isCorrect ? '✓' : '✕'}
            </span>
            <span
              style={{
                fontWeight: 700,
                color: feedback.isCorrect ? '#166534' : '#991B1B',
                fontSize: '14px',
              }}
            >
              {feedback.feedbackTitle}
            </span>
          </div>

          <p style={{ margin: '8px 0', fontSize: '13px', lineHeight: 1.5, color: '#334155' }}>
            {feedback.explanation}
          </p>

          {feedback.sourceRef && (
            <div style={{ marginTop: '8px' }}>
              {renderSourceLink(feedback.sourceRef, true)}
            </div>
          )}

          {feedback.pedagogicalHint && (
            <div
              style={{
                marginTop: '10px',
                padding: '10px 12px',
                borderRadius: '8px',
                backgroundColor: '#FFFBEB',
                border: '1px solid #FEF08A',
                fontSize: '12px',
                color: '#854D0E',
                lineHeight: 1.5,
              }}
            >
              <strong>Gợi ý từ Lumi:</strong> {feedback.pedagogicalHint}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
