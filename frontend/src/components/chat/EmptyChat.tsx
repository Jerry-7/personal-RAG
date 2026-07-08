/**
 * 空聊天占位组件
 *
 * 当没有消息时显示引导内容。
 */

import { MessageSquare } from 'lucide-react';

export function EmptyChat() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center text-gray-400 dark:text-gray-500">
      <MessageSquare className="w-16 h-16 mb-4" />
      <p className="text-lg font-medium">上传文档开始对话</p>
      <p className="text-sm mt-2">
        支持 PDF、Word、TXT、视频等多种格式
      </p>
    </div>
  );
}
