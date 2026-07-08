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

interface AppShellProps {
  children: [ReactNode, ReactNode, ReactNode];
}

export function AppShell({ children }: AppShellProps) {
  const isSidebarOpen = useSidebarStore((s) => s.isOpen);
  const [left, center, right] = children;

  return (
    <div className="h-screen flex flex-col">
      <Header />
      <div
        className="flex-1 grid overflow-hidden"
        style={{
          gridTemplateColumns: `260px 1fr ${isSidebarOpen ? '400px' : '0px'}`,
          transition: 'grid-template-columns 0.3s ease',
        }}
      >
        {/* 左侧导航 */}
        <aside className="border-r border-gray-200 dark:border-gray-700 overflow-y-auto bg-gray-50 dark:bg-gray-800">
          {left}
        </aside>

        {/* 中心聊天区域 */}
        <main className="overflow-hidden flex flex-col">
          {center}
        </main>

        {/* 右侧引用面板 */}
        <aside className="border-l border-gray-200 dark:border-gray-700 overflow-y-auto bg-white dark:bg-gray-900">
          {right}
        </aside>
      </div>
    </div>
  );
}
