import { ApiError, toApiError } from "./client";
import type { StreamEvent } from "./types";

/** The connection dropped before the server sent `done` or `error`. */
export class StreamInterruptedError extends Error {
  constructor() {
    super("Connection to the server was lost while the reply was being generated.");
  }
}

/**
 * POST a JSON body and consume the server-sent event stream it returns.
 * (EventSource cannot POST, so this uses fetch + a ReadableStream parser.)
 *
 * - Non-2xx responses (errors detected before streaming) throw ApiError.
 * - Aborting via `signal` throws a DOMException named "AbortError".
 * - A stream that ends without a terminal event throws StreamInterruptedError.
 */
export async function postSSE(
  path: string,
  body: unknown,
  onEvent: (event: StreamEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  let resp: Response;
  try {
    resp = await fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: { "content-type": "application/json", accept: "text/event-stream" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (signal.aborted) throw err;
    throw new ApiError(0, { code: "network_error", message: "Cannot reach the server. Check your connection." });
  }
  if (!resp.ok) throw await toApiError(resp);
  if (!resp.body) throw new StreamInterruptedError();

  const reader = resp.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  let terminal = false;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += value.replace(/\r\n/g, "\n");
      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const block = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        const parsed = parseBlock(block);
        if (!parsed) continue;
        if (parsed.event === "done" || parsed.event === "error") terminal = true;
        onEvent(parsed);
      }
    }
  } catch (err) {
    if (signal.aborted) throw err;
    throw new StreamInterruptedError();
  } finally {
    reader.releaseLock();
  }
  if (!terminal) throw new StreamInterruptedError();
}

function parseBlock(block: string): StreamEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith(":")) continue;
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (data.length === 0) return null;
  try {
    return { event, data: JSON.parse(data.join("\n")) } as StreamEvent;
  } catch {
    return null;
  }
}
