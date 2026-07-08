/**
 * 来源查询 API
 */

import client from './client';
import type { SourceResponse } from '../types/source';

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
