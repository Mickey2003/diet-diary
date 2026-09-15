import client from './client';

export interface DataSummary {
  meals: number;
  items: number;
  tags: number;
  reports: number;
}

export interface ImportResult {
  imported: number;
  skipped: number;
  errors: string[];
}

export const getDataSummary = () =>
  client.get<DataSummary>('/api/data/summary').then((r) => r.data);

export const importData = (file: File, mode: 'merge' | 'replace') => {
  const fd = new FormData();
  fd.append('file', file);
  fd.append('mode', mode);
  return client
    .post<ImportResult>('/api/data/import', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((r) => r.data);
};
