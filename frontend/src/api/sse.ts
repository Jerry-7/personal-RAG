export interface SSEMessage<T = unknown> {
  event: string;
  data: T;
  id?: string;
}

interface SSEOptions {
  method?: string;
  headers?: HeadersInit;
  body?: BodyInit;
  onMessage: (message: SSEMessage) => void;
  onError: (error: Error) => void;
}

/** Consume a text/event-stream response with correct event boundary handling. */
export function streamSSE(url: string, options: SSEOptions): AbortController {
  const controller = new AbortController();

  void fetch(url, {
    method: options.method,
    headers: options.headers,
    body: options.body,
    signal: controller.signal,
  }).then(async (response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    if (!response.body) throw new Error('响应体为空');

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    const dispatch = (block: string) => {
      let event = 'message';
      let id: string | undefined;
      const dataLines: string[] = [];
      for (const rawLine of block.split('\n')) {
        const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine;
        if (!line || line.startsWith(':')) continue;
        const separator = line.indexOf(':');
        const field = separator < 0 ? line : line.slice(0, separator);
        let value = separator < 0 ? '' : line.slice(separator + 1);
        if (value.startsWith(' ')) value = value.slice(1);
        if (field === 'event') event = value;
        else if (field === 'data') dataLines.push(value);
        else if (field === 'id') id = value;
      }
      if (!dataLines.length) return;
      const rawData = dataLines.join('\n');
      let data: unknown = rawData;
      try { data = JSON.parse(rawData); } catch { /* plain-text SSE data is valid */ }
      options.onMessage({ event, data, id });
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        buffer += decoder.decode();
        if (buffer.trim()) dispatch(buffer);
        break;
      }
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');
      let boundary = buffer.indexOf('\n\n');
      while (boundary >= 0) {
        dispatch(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf('\n\n');
      }
    }
  }).catch((error: unknown) => {
    if (error instanceof Error && error.name !== 'AbortError') options.onError(error);
  });

  return controller;
}
