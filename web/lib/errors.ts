// Turn raw backend/network error strings into something a non-engineer can act
// on. We never want a user to see `HTTP 400: {"detail":"..."}` — that violates
// the "diagnostic hints, not raw tracebacks" rule. Known failure modes get a
// plain-language message + a concrete next step.

export type FriendlyError = {
  message: string;                 // the headline, in plain Chinese
  hint?: string;                   // one line of what to do about it
  action?: 'settings';             // an actionable shortcut the UI can render
};

/** Strip transport wrappers ("HTTP 400:", "chat HTTP 500:") and unwrap a
 *  FastAPI {"detail": "..."} body down to the human-meaningful message. */
function unwrap(raw: string): string {
  let msg = (raw || '').trim();
  msg = msg.replace(/^(?:chat\s+)?HTTP\s+\d+:\s*/i, '').trim();
  // Whole body is JSON {detail: ...}
  try {
    const j = JSON.parse(msg);
    if (j && typeof j === 'object' && typeof (j as { detail?: unknown }).detail === 'string') {
      return (j as { detail: string }).detail.trim();
    }
  } catch { /* not pure JSON — fall through to a regex pull */ }
  const m = msg.match(/"detail"\s*:\s*"((?:[^"\\]|\\.)*)"/);
  if (m) return m[1].replace(/\\"/g, '"').trim();
  return msg;
}

export function humanizeError(raw: string): FriendlyError {
  const msg = unwrap(raw);
  const low = msg.toLowerCase();

  // No model key configured — the single most common "scary" error.
  if (low.includes('no llm key') || (low.includes('llm') && low.includes('key'))) {
    return {
      message: '还没有配置 AI 模型的密钥',
      hint: '这个功能需要 AI 来帮你处理(比如给没见过的格式现写解析器)。请到「设置」里填入一个模型的 API Key,再回来重试。',
      action: 'settings',
    };
  }
  if (low.includes('file too large')) {
    return { message: '文件太大了', hint: '单个文件最大 200 MB,请拆分或压缩后再上传。' };
  }
  if (low.includes('timed out') || low.includes('timeout')) {
    return { message: '处理超时了', hint: '可能是文件较大或网络较慢,稍等一下再点重试。' };
  }
  if (low.includes('failed to fetch') || low.includes('networkerror') || low.includes('load failed')) {
    return { message: '连不上服务器', hint: '检查一下网络,或确认后端服务在运行,然后重试。' };
  }

  // Unknown: at least show the unwrapped message, never the HTTP/JSON wrapper.
  return { message: msg || '出错了,请重试' };
}
