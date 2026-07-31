/**
 * 应用外壳布局组件
 *
 * CSS Grid 三栏布局：
 * - 左侧: 260px 固定宽度 (文档列表)
 * - 中间: 自适应宽度 (聊天区域)
 * - 右侧: 当引用侧边栏打开时 400px，关闭时 0
 */

import type { ReactNode } from 'react';
import { Header } from './Header';
import { useSidebarStore } from '../../store/sidebarStore';
import { useLayoutStore } from '../../store/layoutStore';

interface AppShellProps {
  children: [ReactNode, ReactNode, ReactNode];
}

export function AppShell({ children }: AppShellProps) {
  const isSidebarOpen = useSidebarStore((s) => s.isOpen);
  const isKnowledgeOpen = useLayoutStore((s) => s.isKnowledgeOpen);
  const [left, center, right] = children;

  return (
    <div className="h-screen flex flex-col">
      <Header />
      <div
        className="app-grid flex-1 grid overflow-hidden"
        style={{
          gridTemplateColumns: `260px 1fr ${isSidebarOpen ? '400px' : '0px'}`,
          transition: 'grid-template-columns 0.3s ease',
        }}
      >
        {/* 左侧导航 */}
        <aside className={`app-left border-r border-gray-200 dark:border-gray-700 overflow-y-auto bg-gray-50 dark:bg-gray-800 ${isKnowledgeOpen ? 'is-open' : ''}`}>
          {left}
        </aside>

        {/* 中心聊天区域 */}
        <main className="app-main overflow-hidden flex flex-col">
          {center}
        </main>

        {/* 右侧引用面板 */}
        <aside className={`app-right border-l border-gray-200 dark:border-gray-700 overflow-y-auto bg-white dark:bg-gray-900 ${isSidebarOpen ? 'is-open' : ''}`}>
          {right}
        </aside>
      </div>
    </div>
  );
}
