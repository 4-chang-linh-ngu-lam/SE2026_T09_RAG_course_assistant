import type { DocumentReaderModel } from './domain';
export type ClassSourcePreview = {
  documentId: string;
  classId: string;
  title: string;
  version: number;
  totalPages: number;
  pages: NonNullable<DocumentReaderModel['pageContents']>;
};
