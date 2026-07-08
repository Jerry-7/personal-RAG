/**
 * 顶部导航栏组件
 *
 * 显示应用标题、当前模型名称和设置入口。
 */

import { Settings } from 'lucide-react';
import { useSettingsStore } from '../../store/settingsStore';

export function Header() {
  const openSettings = useSettingsStore((s) => s.openSettings);
  const settings = useSettingsStore((s) => s.settings);

  return (
    <header className="h-14 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between px-4 bg-white dark:bg-gray-900 shrink-0">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold text-gray-900 dark:text-white">
          Personal RAG
        </h1>
        {settings && (
          <span className="text-xs text-gray-500 dark:text-gray-400 bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded-full">
            {settings.llm_provider}: {settings.ollama.llm_model}
          </span>
        )}
      </div>

      <button
        onClick={openSettings}
        className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
        title="Settings"
      >
        <Settings className="w-5 h-5 text-gray-600 dark:text-gray-400" />
      </button>
    </header>
  );
}
