/**
 * 流式文本组件
 *
 * 实时显示 LLM 流式生成的文本，带闪烁光标。
 */

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface StreamingTextProps {
  text: string;
}

export function StreamingText({ text }: StreamingTextProps) {
  if (!text) {
    return <span className="streaming-cursor text-sm leading-relaxed" />;
  }

  return (
    <span className="streaming-cursor text-sm leading-relaxed">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <span>{children}</span>,
        }}
      >
        {text}
      </ReactMarkdown>
    </span>
  );
}
