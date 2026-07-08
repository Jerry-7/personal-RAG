/**
 * 设置弹窗组件
 *
 * 三层 Tab: LLM Provider / Embedding / RAG 参数
 * 支持配置 Ollama URL、API Keys 和模型选择。
 */

import { useState, useEffect } from 'react';
import { X, Check, Eye, EyeOff } from 'lucide-react';
import { useSettingsStore } from '../../store/settingsStore';
import { getSettings, updateSettings, getAvailableModels } from '../../api/settings';
import type { AppSettings, AvailableModels } from '../../types/settings';

type TabKey = 'llm' | 'embedding' | 'rag';

export function SettingsModal() {
  const { closeSettings } = useSettingsStore();
  const [activeTab, setActiveTab] = useState<TabKey>('llm');
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [models, setModels] = useState<AvailableModels | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [showKeys, setShowKeys] = useState(false);

  useEffect(() => {
    Promise.all([getSettings(), getAvailableModels()])
      .then(([s, m]) => {
        setSettings(s);
        setModels(m);
      })
      .catch(console.error);
  }, []);

  if (!settings) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
        <div className="bg-white dark:bg-gray-900 rounded-2xl p-8">
          <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        </div>
      </div>
    );
  }

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await updateSettings(settings as unknown as Record<string, unknown>);
      useSettingsStore.getState().setSettings(settings);
      closeSettings();
    } catch (err) {
      console.error('保存设置失败:', err);
    } finally {
      setIsSaving(false);
    }
  };

  const tabs: { key: TabKey; label: string }[] = [
    { key: 'llm', label: 'LLM 模型' },
    { key: 'embedding', label: 'Embedding' },
    { key: 'rag', label: 'RAG 参数' },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-gray-900 rounded-2xl w-full max-w-lg shadow-2xl">
        {/* 头部 */}
        <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">设置</h2>
          <button onClick={closeSettings} className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tab 导航 */}
        <div className="flex border-b border-gray-200 dark:border-gray-700">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex-1 py-2 text-sm font-medium transition-colors ${
                activeTab === tab.key
                  ? 'text-blue-600 border-b-2 border-blue-600'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab 内容 */}
        <div className="p-4 max-h-96 overflow-y-auto space-y-4">
          {activeTab === 'llm' && (
            <>
              {/* LLM Provider 选择 */}
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">Provider</label>
                <select
                  value={settings.llm_provider}
                  onChange={(e) => setSettings({ ...settings, llm_provider: e.target.value })}
                  className="w-full rounded-lg border px-3 py-2 text-sm bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-600"
                >
                  <option value="ollama">Ollama (本地)</option>
                  <option value="openai">OpenAI (API)</option>
                  <option value="anthropic">Anthropic (API)</option>
                </select>
              </div>

              {/* Ollama 配置 */}
              {settings.llm_provider === 'ollama' && (
                <>
                  <div>
                    <label className="block text-xs font-medium text-gray-500 mb-1">Ollama URL</label>
                    <input
                      type="text"
                      value={settings.ollama.base_url}
                      onChange={(e) =>
                        setSettings({ ...settings, ollama: { ...settings.ollama, base_url: e.target.value } })
                      }
                      className="w-full rounded-lg border px-3 py-2 text-sm bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-600"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-500 mb-1">模型</label>
                    <select
                      value={settings.ollama.llm_model}
                      onChange={(e) =>
                        setSettings({ ...settings, ollama: { ...settings.ollama, llm_model: e.target.value } })
                      }
                      className="w-full rounded-lg border px-3 py-2 text-sm bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-600"
                    >
                      {models?.ollama_llm_models?.map((m) => (
                        <option key={m} value={m}>{m}</option>
                      )) || <option>{settings.ollama.llm_model}</option>}
                    </select>
                  </div>
                </>
              )}

              {/* OpenAI API Key */}
              {settings.llm_provider === 'openai' && (
                <ApiKeyInput
                  label="OpenAI API Key"
                  value={settings.openai.api_key || ''}
                  show={showKeys}
                  onToggleShow={() => setShowKeys(!showKeys)}
                  onChange={(val) => setSettings({ ...settings, openai: { ...settings.openai, api_key: val } })}
                />
              )}

              {/* Anthropic API Key */}
              {settings.llm_provider === 'anthropic' && (
                <ApiKeyInput
                  label="Anthropic API Key"
                  value={settings.anthropic.api_key || ''}
                  show={showKeys}
                  onToggleShow={() => setShowKeys(!showKeys)}
                  onChange={(val) => setSettings({ ...settings, anthropic: { ...settings.anthropic, api_key: val } })}
                />
              )}
            </>
          )}

          {activeTab === 'embedding' && (
            <>
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">Embedding Provider</label>
                <select
                  value={settings.embedding_provider}
                  onChange={(e) => setSettings({ ...settings, embedding_provider: e.target.value })}
                  className="w-full rounded-lg border px-3 py-2 text-sm bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-600"
                >
                  <option value="ollama">Ollama (本地)</option>
                  <option value="openai">OpenAI (API)</option>
                </select>
              </div>

              {settings.embedding_provider === 'ollama' && (
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">Embedding 模型</label>
                  <select
                    value={settings.ollama.embedding_model}
                    onChange={(e) =>
                      setSettings({ ...settings, ollama: { ...settings.ollama, embedding_model: e.target.value } })
                    }
                    className="w-full rounded-lg border px-3 py-2 text-sm bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-600"
                  >
                    {models?.ollama_embed_models?.map((m) => (
                      <option key={m} value={m}>{m}</option>
                    )) || <option>{settings.ollama.embedding_model}</option>}
                  </select>
                </div>
              )}
            </>
          )}

          {activeTab === 'rag' && (
            <>
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">
                  分块大小: {settings.rag.chunk_size}
                </label>
                <input
                  type="range"
                  min={100}
                  max={5000}
                  step={100}
                  value={settings.rag.chunk_size}
                  onChange={(e) =>
                    setSettings({ ...settings, rag: { ...settings.rag, chunk_size: parseInt(e.target.value) } })
                  }
                  className="w-full"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">
                  分块重叠: {settings.rag.chunk_overlap}
                </label>
                <input
                  type="range"
                  min={0}
                  max={2000}
                  step={50}
                  value={settings.rag.chunk_overlap}
                  onChange={(e) =>
                    setSettings({ ...settings, rag: { ...settings.rag, chunk_overlap: parseInt(e.target.value) } })
                  }
                  className="w-full"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">
                  检索数量: {settings.rag.retrieval_top_k}
                </label>
                <input
                  type="range"
                  min={1}
                  max={50}
                  step={1}
                  value={settings.rag.retrieval_top_k}
                  onChange={(e) =>
                    setSettings({ ...settings, rag: { ...settings.rag, retrieval_top_k: parseInt(e.target.value) } })
                  }
                  className="w-full"
                />
              </div>
            </>
          )}
        </div>

        {/* 底部按钮 */}
        <div className="flex justify-end gap-2 p-4 border-t border-gray-200 dark:border-gray-700">
          <button
            onClick={closeSettings}
            className="px-4 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
          >
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={isSaving}
            className="px-4 py-2 text-sm rounded-lg bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-50 transition-colors flex items-center gap-2"
          >
            <Check className="w-4 h-4" />
            {isSaving ? '保存中...' : '保存'}
          </button>
        </div>
      </div>
    </div>
  );
}

/** API Key 输入组件 */
function ApiKeyInput({
  label,
  value,
  show,
  onToggleShow,
  onChange,
}: {
  label: string;
  value: string;
  show: boolean;
  onToggleShow: () => void;
  onChange: (val: string) => void;
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-500 mb-1">{label}</label>
      <div className="flex gap-1">
        <input
          type={show ? 'text' : 'password'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="sk-..."
          className="flex-1 rounded-lg border px-3 py-2 text-sm bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-600"
        />
        <button onClick={onToggleShow} className="px-2 rounded-lg border hover:bg-gray-50 dark:hover:bg-gray-800">
          {show ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
        </button>
      </div>
    </div>
  );
}
