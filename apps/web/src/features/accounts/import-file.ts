import type { ImportCell, ImportFile } from '@/lib/accounts';

export class ImportFileError extends Error {}

// Parses RFC4180-style fields while retaining each source row's first physical line.
export function parseCsv(text: string, filename: string): ImportFile {
  const source = text.replace(/^\uFEFF/u, '');
  const parsed: { rowNumber: number; cells: string[] }[] = [];
  let cells: string[] = [], field = '', quoted = false, closed = false;
  let line = 1, rowStart = 1;
  const finishField = () => { cells.push(field); field = ''; closed = false; };
  const finishRow = () => { finishField(); if (cells.some(cell => cell.trim())) parsed.push({ rowNumber: rowStart, cells }); cells = []; rowStart = line + 1; };
  for (let index = 0; index < source.length; index++) {
    const character = source[index];
    if (quoted) {
      if (character === '"') { if (source[index + 1] === '"') { field += '"'; index++; } else { quoted = false; closed = true; } }
      else { field += character; if (character === '\n') line++; else if (character === '\r' && source[index + 1] !== '\n') line++; }
      continue;
    }
    if (character === '"') { if (field || closed) throw new ImportFileError(`Dấu nháy không hợp lệ ở dòng ${line}.`); quoted = true; continue; }
    if (character === ',') { finishField(); continue; }
    if (character === '\n' || character === '\r') { finishRow(); if (character === '\r' && source[index + 1] === '\n') index++; line++; continue; }
    if (closed) throw new ImportFileError(`Có nội dung sau dấu nháy đóng ở dòng ${line}.`);
    field += character;
  }
  if (quoted) throw new ImportFileError(`Chưa đóng dấu nháy ở dòng ${rowStart}.`);
  if (field || cells.length || closed) { finishField(); if (cells.some(cell => cell.trim())) parsed.push({ rowNumber: rowStart, cells }); }
  return fromRows(parsed, filename);
}

export function fromRows(rows: { rowNumber: number; cells: ImportCell[] }[], filename: string): ImportFile {
  const populated = rows.filter(row => row.cells.some(cell => cell !== null && String(cell).trim()));
  const first = populated[0];
  if (!first || !populated.slice(1).length) throw new ImportFileError('Tệp cần có một dòng tiêu đề và ít nhất một dòng học sinh.');
  if (first.cells.some(cell => typeof cell !== 'string' || !cell.trim())) throw new ImportFileError('Tiêu đề cột phải là văn bản không rỗng.');
  const headers = first.cells.map(cell => String(cell).trim());
  if (new Set(headers.map(header => header.toLowerCase())).size !== headers.length) throw new ImportFileError('Tên cột tiêu đề bị trùng.');
  if (populated.slice(1).some(row => row.cells.length > headers.length)) throw new ImportFileError('Có dòng nhiều ô hơn số cột tiêu đề. Hãy kiểm tra dấu phẩy hoặc tệp nguồn.');
  return { filename, headers, rows: populated.slice(1).map(row => ({ rowNumber: row.rowNumber, cells: [...row.cells] })) };
}

export function normalizeImportCells(cells: readonly unknown[]): ImportCell[] { return cells.map(cell => { if (cell === null || typeof cell === 'string' || typeof cell === 'number' || typeof cell === 'boolean' || cell instanceof Date) return cell; throw new ImportFileError('Bảng tính có ô không đọc được. Hãy lưu lại tệp XLSX và kiểm tra nội dung.'); }); }

export async function readImportFile(file: File): Promise<ImportFile> {
  if (!file.size) throw new ImportFileError('Tệp đã chọn đang rỗng.');
  const extension = file.name.split('.').pop()?.toLowerCase();
  if (extension === 'csv') {
    let text: string;
    try { text = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer()); }
    catch { throw new ImportFileError('Không đọc được mã hóa tệp. Hãy lưu CSV bằng UTF-8 và chọn lại.'); }
    return parseCsv(text, file.name);
  }
  if (extension === 'xlsx') {
    try {
      const { readSheet } = await import('read-excel-file/browser');
      const rows = await readSheet(file);
      return fromRows(rows.map((cells, index) => ({ rowNumber: index + 1, cells: normalizeImportCells(cells) })), file.name);
    } catch (error) {
      if (error instanceof ImportFileError) throw error;
      throw new ImportFileError('Không đọc được bảng tính. Hãy kiểm tra đây là tệp XLSX hợp lệ, không có mật khẩu.');
    }
  }
  throw new ImportFileError('Hãy chọn tệp CSV UTF-8 hoặc Excel XLSX. Định dạng XLS cũ chưa được hỗ trợ.');
}

export function importErrorsCsv(rows: { rowNumber: number; username: string; displayName: string; errors: string[] }[]) {
  const escape = (value: string) => `"${(/^[\t\r\n =+@-]/u.test(value) ? "'" : '') + value.replaceAll('"', '""')}"`;
  return '\uFEFF' + [['Dòng', 'Tên đăng nhập', 'Họ tên', 'Lỗi'], ...rows.filter(row => row.errors.length).map(row => [String(row.rowNumber), row.username, row.displayName, row.errors.join('; ')])].map(row => row.map(escape).join(',')).join('\r\n');
}
