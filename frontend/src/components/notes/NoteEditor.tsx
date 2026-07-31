import { useEffect, useState } from 'react';
import { Archive, BookOpenCheck, Database, Plus, Save, Trash2, X } from 'lucide-react';
import { createCollection, createTag, deleteNote, getNote, indexNote, listCollections, listTags, publishNote, removeNoteIndex, updateNote } from '../../api/notes';
import { useNoteStore } from '../../store/noteStore';
import { useSidebarStore } from '../../store/sidebarStore';
import type { TaxonomyItem } from '../../types/note';

export function NoteEditor() {
  const draft = useSidebarStore((state) => state.activeDraft);
  const close = useSidebarStore((state) => state.closeSidebar);
  const updateDraft = useSidebarStore((state) => state.updateDraft);
  const upsertNote = useNoteStore((state) => state.upsertNote);
  const removeNote = useNoteStore((state) => state.removeNote);
  const [title, setTitle] = useState(draft?.title || '');
  const [summary, setSummary] = useState(draft?.summary || '');
  const [content, setContent] = useState(draft?.content_md || '');
  const [tagIds, setTagIds] = useState<string[]>(draft?.tags.map((item) => item.id) || []);
  const [collectionIds, setCollectionIds] = useState<string[]>(draft?.collections.map((item) => item.id) || []);
  const [tags, setTags] = useState<TaxonomyItem[]>([]);
  const [collections, setCollections] = useState<TaxonomyItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [newTag, setNewTag] = useState('');
  const [newCollection, setNewCollection] = useState('');

  useEffect(() => { void Promise.all([listTags(), listCollections()]).then(([t, c]) => { setTags(t); setCollections(c); }); }, []);
  useEffect(() => {
    if (!draft) return;
    setTitle(draft.title); setSummary(draft.summary); setContent(draft.content_md);
    setTagIds(draft.tags.map((item) => item.id));
    setCollectionIds(draft.collections.map((item) => item.id));
  }, [draft?.id]);
  if (!draft) return null;

  const save = async (extra: Record<string, unknown> = {}) => {
    setBusy(true);
    try {
      const note = await updateNote(draft.id, { title, summary, content_md: content, tag_ids: tagIds, collection_ids: collectionIds, ...extra });
      updateDraft(note); upsertNote(note); return note;
    } finally { setBusy(false); }
  };

  const toggle = (id: string, values: string[], setter: (values: string[]) => void) => setter(values.includes(id) ? values.filter((item) => item !== id) : [...values, id]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-gray-200 p-4 dark:border-gray-700">
        <div><p className="text-sm font-semibold">笔记草稿</p><p className="text-[10px] text-gray-500">{draft.status} · {draft.index_status}</p></div>
        <button title="关闭" onClick={close}><X className="h-4 w-4 text-gray-500" /></button>
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        <input value={title} onChange={(event) => setTitle(event.target.value)} className="w-full border-b border-gray-200 bg-transparent pb-2 text-base font-semibold outline-none dark:border-gray-700" />
        <textarea value={summary} onChange={(event) => setSummary(event.target.value)} rows={3} placeholder="摘要" className="w-full resize-none rounded border border-gray-200 bg-transparent p-2 text-xs outline-none dark:border-gray-700" />
        <textarea value={content} onChange={(event) => setContent(event.target.value)} className="min-h-80 w-full resize-y rounded border border-gray-200 bg-transparent p-3 font-mono text-xs leading-5 outline-none dark:border-gray-700" />
        <Taxonomy label="标签" items={tags} selected={tagIds} onToggle={(id) => toggle(id, tagIds, setTagIds)} />
        <InlineCreate value={newTag} setValue={setNewTag} placeholder="新标签" onCreate={() => void createTag(newTag.trim()).then((item) => { setTags((current) => [...current, item]); setTagIds((current) => [...current, item.id]); setNewTag(''); })} />
        {!!draft.suggested_tags?.length && <div><p className="mb-1 text-xs font-medium text-gray-500">建议标签</p><p className="text-xs text-gray-500">{draft.suggested_tags.join(' · ')}</p></div>}
        <Taxonomy label="集合" items={collections} selected={collectionIds} onToggle={(id) => toggle(id, collectionIds, setCollectionIds)} />
        <InlineCreate value={newCollection} setValue={setNewCollection} placeholder="新集合" onCreate={() => void createCollection(newCollection.trim()).then((item) => { setCollections((current) => [...current, item]); setCollectionIds((current) => [...current, item.id]); setNewCollection(''); })} />
        {!!draft.sources.length && <p className="text-[11px] text-gray-500">已固定 {draft.sources.length} 个来源版本</p>}
      </div>
      <div className="flex flex-wrap gap-2 border-t border-gray-200 p-3 dark:border-gray-700">
        <button disabled={busy} onClick={() => void save()} className="flex items-center gap-1 rounded bg-blue-600 px-3 py-2 text-xs text-white"><Save className="h-3.5 w-3.5" />保存</button>
        {draft.status === 'draft' && <button disabled={busy} onClick={() => void save().then(() => publishNote(draft.id)).then((note) => { updateDraft(note); upsertNote(note); })} className="flex items-center gap-1 rounded border px-3 py-2 text-xs"><BookOpenCheck className="h-3.5 w-3.5" />发布</button>}
        {draft.status === 'published' && draft.index_status !== 'indexed' && <button disabled={busy} onClick={() => void save().then(() => indexNote(draft.id)).then(() => getNote(draft.id)).then((note) => { updateDraft(note); upsertNote(note); })} className="flex items-center gap-1 rounded border px-3 py-2 text-xs"><Database className="h-3.5 w-3.5" />加入知识库</button>}
        {draft.index_status === 'indexed' && <button onClick={() => void removeNoteIndex(draft.id).then(() => getNote(draft.id)).then((note) => { updateDraft(note); upsertNote(note); })} className="rounded border px-3 py-2 text-xs">移出知识库</button>}
        <button onClick={() => void save({ status: 'archived' })} title="归档" className="rounded border p-2"><Archive className="h-3.5 w-3.5" /></button>
        <button onClick={() => void deleteNote(draft.id).then(() => { removeNote(draft.id); close(); })} title="放弃并删除" className="ml-auto rounded border border-red-200 p-2 text-red-600"><Trash2 className="h-3.5 w-3.5" /></button>
      </div>
    </div>
  );
}

function Taxonomy({ label, items, selected, onToggle }: { label: string; items: TaxonomyItem[]; selected: string[]; onToggle: (id: string) => void }) {
  return <div><p className="mb-2 text-xs font-medium text-gray-500">{label}</p><div className="flex flex-wrap gap-2">{items.map((item) => <label key={item.id} className="flex items-center gap-1 text-xs"><input type="checkbox" checked={selected.includes(item.id)} onChange={() => onToggle(item.id)} />{item.name}</label>)}{!items.length && <span className="text-[11px] text-gray-400">暂无{label}</span>}</div></div>;
}

function InlineCreate({ value, setValue, placeholder, onCreate }: { value: string; setValue: (value: string) => void; placeholder: string; onCreate: () => void }) {
  return <div className="flex gap-1"><input value={value} onChange={(event) => setValue(event.target.value)} placeholder={placeholder} className="min-w-0 flex-1 rounded border border-gray-200 bg-transparent px-2 py-1.5 text-xs outline-none dark:border-gray-700" /><button disabled={!value.trim()} onClick={onCreate} title={`创建${placeholder}`} className="rounded border border-gray-200 p-1.5 disabled:opacity-40 dark:border-gray-700"><Plus className="h-3.5 w-3.5" /></button></div>;
}
