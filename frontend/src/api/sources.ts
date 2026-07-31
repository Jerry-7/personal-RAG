/**
 * 来源查询 API
 */

import client from './client';
import type { NoteSourceResponse, SourceResponse, WebSourceResponse } from '../types/source';

/** 获取引用来源的完整内容 */
export async function getSourceChunk(
  docId: string,
  chunkId: string
): Promise<SourceResponse> {
  const { data } = await client.get<SourceResponse>(
    `/sources/${docId}/chunks/${chunkId}`
  );
  return data;
}

export async function getWebSnapshot(snapshotId: string): Promise<WebSourceResponse> {
  return (await client.get<WebSourceResponse>(`/sources/web/${snapshotId}`)).data;
}

export async function getNoteSource(noteId: string): Promise<NoteSourceResponse> {
  return (await client.get<NoteSourceResponse>(`/sources/notes/${noteId}`)).data;
}
