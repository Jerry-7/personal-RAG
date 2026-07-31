/**
 * 引用侧边栏状态管理 (Zustand)
 *
 * 控制右侧 CitationSidebar 的开关和内容。
 * 支持多个引用堆叠展示。
 */

import { create } from 'zustand';
import type { CitationData } from '../types/chat';
import type { NoteItem } from '../types/note';

interface SidebarState {
  /** 侧边栏是否打开 */
  isOpen: boolean;
  /** 当前展示的引用列表 */
  activeCitations: CitationData[];
  /** 当前激活查看的引用索引（用于高亮） */
  activeCitationIndex: number | null;
  /** 是否正在加载来源数据 */
  isLoading: boolean;
  activeDraft: NoteItem | null;

  // Actions
  openSource: (citation: CitationData) => void;
  setActiveCitation: (index: number) => void;
  closeSidebar: () => void;
  setLoading: (loading: boolean) => void;
  openDraft: (note: NoteItem) => void;
  updateDraft: (note: NoteItem) => void;
}

export const useSidebarStore = create<SidebarState>((set, get) => ({
  isOpen: false,
  activeCitations: [],
  activeCitationIndex: null,
  isLoading: false,
  activeDraft: null,

  openSource: (citation) => {
    const state = get();
    // 避免重复添加同一引用
    const sourceKey = citation.snapshot_id || citation.chunk_id || citation.source_id;
    const existing = state.activeCitations.filter((c) => (c.snapshot_id || c.chunk_id || c.source_id) === sourceKey);
    const citations = existing.length > 0
      ? state.activeCitations
      : [...state.activeCitations, citation];
    set({
      isOpen: true,
      activeCitations: citations,
      activeCitationIndex: citation.index,
      activeDraft: null,
    });
  },

  setActiveCitation: (index) => set({ activeCitationIndex: index }),

  closeSidebar: () =>
    set({ isOpen: false, activeCitations: [], activeCitationIndex: null, activeDraft: null }),

  setLoading: (loading) => set({ isLoading: loading }),
  openDraft: (note) => set({ isOpen: true, activeDraft: note, activeCitations: [], activeCitationIndex: null }),
  updateDraft: (note) => set({ activeDraft: note }),
}));
