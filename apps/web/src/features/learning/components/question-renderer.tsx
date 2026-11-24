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
import { Icon } from '@/components/ui';

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
        <span className="qr-source-unavailable">
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
        data-testid={isFeedback ? 'feedback-source-ref-link' : 'question-source-ref-link'}
      >
        <Icon name="book" />
        <span>{isFeedback ? 'Trích dẫn' : 'Nguồn'}: {displayText}</span>
      </Link>
    );
  };

  return (
    <div className="card question-card qr-card">
      <div className="qr-header">
        <div className="qr-header-main">
          <span className="qr-number-badge">
            Câu {questionNumber}
          </span>
          {question.topic && (
            <span className="qr-topic">
              {question.topic}
            </span>
          )}
        </div>
        {typeof question.points === 'number' && (
          <span className="qr-points-badge">
            {question.points} điểm
          </span>
        )}
      </div>

      <div className="qr-prompt">
        {question.prompt}
      </div>

      {question.sourceRef && (
        <div className="qr-source-wrap">
          {renderSourceLink(question.sourceRef, false)}
        </div>
      )}

      {/* Single Choice Form */}
      {question.type === 'single_choice' && (
        <div
          className="qr-options"
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
                className={`qr-option${isSelected ? ' is-selected' : ''}${readOnly ? ' is-readonly' : ''}`}
              >
                <input
                  id={inputId}
                  type="radio"
                  name={singleChoiceName}
                  value={opt.id}
                  checked={isSelected}
                  disabled={readOnly}
                  onChange={() => handleSingleChoice(opt.id)}
                />
                <span className="qr-option-label">{opt.label}.</span>
                <span className="qr-option-text">{opt.text}</span>
              </label>
            );
          })}
        </div>
      )}

      {/* Multiple Choice Form */}
      {question.type === 'multiple_choice' && (
        <div
          className="qr-options"
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
                className={`qr-option${isChecked ? ' is-selected' : ''}${readOnly ? ' is-readonly' : ''}`}
              >
                <input
                  id={inputId}
                  type="checkbox"
                  name={`mc_${question.id}_${uniqueId}`}
                  value={opt.id}
                  checked={isChecked}
                  disabled={readOnly}
                  onChange={() => handleMultipleChoice(opt.id)}
                />
                <span className="qr-option-label">{opt.label}.</span>
                <span className="qr-option-text">{opt.text}</span>
              </label>
            );
          })}
        </div>
      )}

      {/* True/False Form */}
      {question.type === 'true_false' && (
        <div className="table-scroll qr-tf-wrap">
          <table className="qr-tf-table">
            <thead>
              <tr>
                <th>Mệnh đề</th>
                <th className="qr-tf-col-choice">
                  Đúng
                </th>
                <th className="qr-tf-col-choice">
                  Sai
                </th>
              </tr>
            </thead>
            <tbody>
              {(question as TrueFalseQuestion).statements.map(stmt => {
                const currentVal = answer?.trueFalseValues?.[stmt.id];
                const stmtRadioName = `tf_${question.id}_${stmt.id}_${uniqueId}`;
                return (
                  <tr key={stmt.id}>
                    <td className="qr-tf-stmt">
                      <strong>{stmt.label})</strong>
                      <span>{stmt.text}</span>
                    </td>
                    <td className="qr-tf-cell">
                      <label className={`qr-tf-choice${readOnly ? ' is-readonly' : ''}`}>
                        <input
                          type="radio"
                          name={stmtRadioName}
                          value="true"
                          checked={currentVal === true}
                          disabled={readOnly}
                          aria-label={`Mệnh đề ${stmt.label}: ${stmt.text} — Chọn Đúng`}
                          onChange={() => handleTrueFalse(stmt.id, true)}
                        />
                      </label>
                    </td>
                    <td className="qr-tf-cell">
                      <label className={`qr-tf-choice${readOnly ? ' is-readonly' : ''}`}>
                        <input
                          type="radio"
                          name={stmtRadioName}
                          value="false"
                          checked={currentVal === false}
                          disabled={readOnly}
                          aria-label={`Mệnh đề ${stmt.label}: ${stmt.text} — Chọn Sai`}
                          onChange={() => handleTrueFalse(stmt.id, false)}
                        />
                      </label>
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
        <div className="qr-short-answer">
          <label
            htmlFor={shortAnswerId}
            className="qr-short-answer-label"
          >
            Nhập câu trả lời ngắn:
          </label>
          <input
            id={shortAnswerId}
            type="text"
            className="input qr-short-answer-input"
            placeholder="Nhập câu trả lời của bạn..."
            value={answer?.shortAnswerValue ?? ''}
            disabled={readOnly}
            onChange={handleShortAnswer}
          />
        </div>
      )}

      {/* Immediate Feedback Card */}
      {feedback && (
        <div
          data-testid="feedback-card"
          className={`qr-feedback ${feedback.isCorrect ? 'is-correct' : 'is-incorrect'}`}
        >
          <div className="qr-feedback-header">
            <span className="qr-feedback-icon" aria-hidden="true">
              {feedback.isCorrect ? '✓' : '✕'}
            </span>
            <span className="qr-feedback-title">
              {feedback.feedbackTitle}
            </span>
          </div>

          <p className="qr-feedback-explanation">
            {feedback.explanation}
          </p>

          {feedback.sourceRef && (
            <div className="qr-feedback-source">
              {renderSourceLink(feedback.sourceRef, true)}
            </div>
          )}

          {feedback.pedagogicalHint && (
            <div className="qr-feedback-hint">
              <strong>Gợi ý từ Lumi:</strong> {feedback.pedagogicalHint}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
