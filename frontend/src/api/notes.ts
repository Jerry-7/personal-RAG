import client from './client';
import type { NoteItem, TaxonomyItem } from '../types/note';

export async function listNotes(params?: Record<string, string>): Promise<{ notes: NoteItem[]; total: number }> {
  return (await client.get('/notes', { params })).data;
}

export async function getNote(id: string): Promise<NoteItem> {
  return (await client.get(`/notes/${id}`)).data;
}

export async function updateNote(id: string, payload: Partial<NoteItem> & { tag_ids?: string[]; collection_ids?: string[] }): Promise<NoteItem> {
  return (await client.put(`/notes/${id}`, payload)).data;
}

export async function deleteNote(id: string): Promise<void> {
  await client.delete(`/notes/${id}`);
}

export async function draftFromConversation(conversationId: string): Promise<NoteItem> {
  return (await client.post('/notes/drafts/from-conversation', { conversation_id: conversationId })).data;
}

export async function publishNote(id: string): Promise<NoteItem> {
  return (await client.post(`/notes/${id}/publish`)).data;
}

export async function indexNote(id: string): Promise<void> {
  await client.post(`/notes/${id}/index`);
}

export async function removeNoteIndex(id: string): Promise<void> {
  await client.delete(`/notes/${id}/index`);
}

export async function listTags(): Promise<TaxonomyItem[]> {
  return (await client.get('/tags')).data;
}

export async function listCollections(): Promise<TaxonomyItem[]> {
  return (await client.get('/collections')).data;
}

export async function createTag(name: string): Promise<TaxonomyItem> {
  return (await client.post('/tags', { name })).data;
}

export async function createCollection(name: string): Promise<TaxonomyItem> {
  return (await client.post('/collections', { name, description: '' })).data;
}
