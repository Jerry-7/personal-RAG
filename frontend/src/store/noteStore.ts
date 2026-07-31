import { create } from 'zustand';
import type { NoteItem } from '../types/note';

interface NoteState {
  notes: NoteItem[];
  setNotes: (notes: NoteItem[]) => void;
  upsertNote: (note: NoteItem) => void;
  removeNote: (id: string) => void;
}

export const useNoteStore = create<NoteState>((set) => ({
  notes: [],
  setNotes: (notes) => set({ notes }),
  upsertNote: (note) => set((state) => ({ notes: [note, ...state.notes.filter((item) => item.id !== note.id)] })),
  removeNote: (id) => set((state) => ({ notes: state.notes.filter((item) => item.id !== id) })),
}));
