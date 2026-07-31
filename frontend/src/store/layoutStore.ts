import { create } from 'zustand';

interface LayoutState {
  isKnowledgeOpen: boolean;
  toggleKnowledge: () => void;
  closeKnowledge: () => void;
}

export const useLayoutStore = create<LayoutState>((set) => ({
  isKnowledgeOpen: false,
  toggleKnowledge: () => set((state) => ({ isKnowledgeOpen: !state.isKnowledgeOpen })),
  closeKnowledge: () => set({ isKnowledgeOpen: false }),
}));
