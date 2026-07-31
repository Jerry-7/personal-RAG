import { useEffect, useState } from 'react';
import { Archive, BookOpen, FileText, Search } from 'lucide-react';
import { DocumentUploader } from '../documents/DocumentUploader';
import { DocumentList } from '../documents/DocumentList';
import { listCollections, listNotes, listTags } from '../../api/notes';
import type { TaxonomyItem } from '../../types/note';
import { useNoteStore } from '../../store/noteStore';
import { useSidebarStore } from '../../store/sidebarStore';
import { useLayoutStore } from '../../store/layoutStore';

export function KnowledgeSidebar() {
  const [tab, setTab] = useState<'documents' | 'notes'>('documents');
  const [query, setQuery] = useState('');
  const [archived, setArchived] = useState(false);
  const [tagId, setTagId] = useState('');
  const [collectionId, setCollectionId] = useState('');
  const [tags, setTags] = useState<TaxonomyItem[]>([]);
  const [collections, setCollections] = useState<TaxonomyItem[]>([]);
  const notes = useNoteStore((state) => state.notes);
  const setNotes = useNoteStore((state) => state.setNotes);
  const closeKnowledge = useLayoutStore((state) => state.closeKnowledge);

  useEffect(() => { void listNotes().then((result) => setNotes(result.notes)); }, [setNotes]);

  useEffect(() => {
    if (tab !== 'notes') return;
    void listNotes({ ...(query ? { query } : {}), ...(archived ? { status: 'archived' } : {}), ...(tagId ? { tag_id: tagId } : {}), ...(collectionId ? { collection_id: collectionId } : {}) })
      .then((result) => setNotes(result.notes));
  }, [tab, query, archived, tagId, collectionId, setNotes]);
  useEffect(() => { if (tab === 'notes') void Promise.all([listTags(), listCollections()]).then(([t, c]) => { setTags(t); setCollections(c); }); }, [tab]);

  return (
    <div className="flex h-full flex-col">
      <div className="grid grid-cols-2 border-b border-gray-200 dark:border-gray-700">
        <button onClick={() => setTab('documents')} className={`flex items-center justify-center gap-1.5 py-3 text-xs ${tab === 'documents' ? 'border-b-2 border-blue-600 text-blue-600' : 'text-gray-500'}`}>
          <FileText className="h-4 w-4" />文档
        </button>
        <button onClick={() => setTab('notes')} className={`flex items-center justify-center gap-1.5 py-3 text-xs ${tab === 'notes' ? 'border-b-2 border-blue-600 text-blue-600' : 'text-gray-500'}`}>
          <BookOpen className="h-4 w-4" />笔记
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        {tab === 'documents' ? <div className="space-y-4"><DocumentUploader /><DocumentList /></div> : (
          <div className="space-y-3">
            <div className="flex items-center gap-2 rounded border border-gray-200 bg-white px-2 dark:border-gray-700 dark:bg-gray-900">
              <Search className="h-3.5 w-3.5 text-gray-400" />
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索笔记" className="min-w-0 flex-1 bg-transparent py-2 text-xs outline-none" />
              <button title="归档" onClick={() => setArchived(!archived)} className={archived ? 'text-blue-600' : 'text-gray-400'}><Archive className="h-3.5 w-3.5" /></button>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <select value={tagId} onChange={(event) => setTagId(event.target.value)} className="min-w-0 rounded border border-gray-200 bg-white px-2 py-1.5 text-[11px] dark:border-gray-700 dark:bg-gray-900"><option value="">全部标签</option>{tags.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
              <select value={collectionId} onChange={(event) => setCollectionId(event.target.value)} className="min-w-0 rounded border border-gray-200 bg-white px-2 py-1.5 text-[11px] dark:border-gray-700 dark:bg-gray-900"><option value="">全部集合</option>{collections.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
            </div>
            {notes.map((note) => (
              <button key={note.id} onClick={() => { useSidebarStore.getState().openDraft(note); closeKnowledge(); }} className="w-full rounded border border-gray-200 bg-white p-3 text-left dark:border-gray-700 dark:bg-gray-800">
                <p className="truncate text-xs font-medium text-gray-800 dark:text-gray-200">{note.title}</p>
                <p className="mt-1 text-[10px] text-gray-500">{note.status} · {note.index_status}</p>
              </button>
            ))}
            {!notes.length && <p className="py-6 text-center text-xs text-gray-400">暂无笔记</p>}
          </div>
        )}
      </div>
    </div>
  );
}
