/**
 * Client for the Divya API.
 *
 * Every failure path returns a typed error rather than throwing a raw `fetch` rejection, so
 * the UI can degrade visibly. A market terminal that blanks when the backend is down is worse
 * than one that says the backend is down.
 */

import type {
  CommandResponse,
  Health,
  Session,
  SessionSummary,
  StreamResponse,
  Workspace,
} from "./divya-types";

export const API_BASE =
  process.env.NEXT_PUBLIC_DIVYA_API ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly offline: boolean,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    // Network-level failure: the backend is not running. This is a *degraded* state, not an
    // empty one, and the UI must be able to say which.
    throw new ApiError(
      `backend unreachable at ${API_BASE} — start it with \`divya serve\``,
      0,
      true,
    );
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail ?? detail;
    } catch {
      /* body was not JSON; the status text is the best we have */
    }
    throw new ApiError(`${res.status} ${detail}`, res.status, false);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => req<Health>("/health"),

  stream: (limit = 200) =>
    req<StreamResponse>(`/stream?limit=${limit}&measurable_only=true`),

  company: (symbol: string, limit = 40) =>
    req<{ symbol: string; company: string; history: unknown[] }>(
      `/company/${encodeURIComponent(symbol)}?limit=${limit}`,
    ),

  sessions: () => req<{ sessions: SessionSummary[] }>("/sessions"),

  session: (taskId: string) => req<Session>(`/sessions/${encodeURIComponent(taskId)}`),

  workspace: (taskId: string) =>
    req<Workspace>(`/workspace/${encodeURIComponent(taskId)}`),

  /**
   * Send an utterance. Supplying `task_id` is what makes it a follow-up: the backend keeps
   * the entities under investigation and narrows the current task rather than starting over.
   */
  command: (text: string, taskId?: string, decide = false) =>
    req<CommandResponse>("/command", {
      method: "POST",
      body: JSON.stringify({ text, task_id: taskId ?? null, decide }),
    }),
};
