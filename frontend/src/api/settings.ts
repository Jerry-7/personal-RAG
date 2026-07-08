/**
 * 设置 API
 */

import client from './client';
import type { AppSettings, AvailableModels } from '../types/settings';

/** 获取当前设置 */
export async function getSettings(): Promise<AppSettings> {
  const { data } = await client.get<AppSettings>('/settings');
  return data;
}

/** 更新设置（部分更新） */
export async function updateSettings(updates: Record<string, unknown>): Promise<void> {
  await client.put('/settings', updates);
}

/** 获取可用模型列表 */
export async function getAvailableModels(): Promise<AvailableModels> {
  const { data } = await client.get<AvailableModels>('/models');
  return data;
}
