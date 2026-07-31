export interface TaxonomyItem {
  id: string;
  name: string;
  description?: string;
}

export interface NoteItem {
  id: string;
  title: string;
  summary: string;
  content_md: string;
  status: 'draft' | 'published' | 'archived';
  index_status: 'not_indexed' | 'indexing' | 'indexed' | 'stale';
  conversation_id?: string;
  source_message_id?: string;
  tags: TaxonomyItem[];
  collections: TaxonomyItem[];
  sources: Array<Record<string, unknown>>;
  suggested_tags: string[];
  created_at: string;
  updated_at: string;
}
