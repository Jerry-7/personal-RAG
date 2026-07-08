/**
 * 设置状态管理 (Zustand)
 */

import { create } from 'zustand';
import type { AppSettings } from '../types/settings';

interface SettingsState {
  settings: AppSettings | null;
  isLoading: boolean;
  isSettingsOpen: boolean;

  // Actions
  setSettings: (settings: AppSettings) => void;
  setLoading: (loading: boolean) => void;
  openSettings: () => void;
  closeSettings: () => void;
}

export const useSettingsStore = create<SettingsState>((set) => ({
  settings: null,
  isLoading: false,
  isSettingsOpen: false,

  setSettings: (settings) => set({ settings }),
  setLoading: (loading) => set({ isLoading: loading }),
  openSettings: () => set({ isSettingsOpen: true }),
  closeSettings: () => set({ isSettingsOpen: false }),
}));
