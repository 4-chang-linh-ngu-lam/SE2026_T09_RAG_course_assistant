import type { DocumentReaderModel } from './domain';
export type ClassSourcePreview = {
  locatorLabel?: 'Trang'|'Slide'|'Mục';
  documentId: string;
  classId: string;
  title: string;
  version: number;
  totalPages: number;
  pages: NonNullable<DocumentReaderModel['pageContents']>;
};
