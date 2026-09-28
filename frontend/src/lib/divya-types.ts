/**
 * Typed mirror of the backend's UI-intent protocol.
 *
 * The backend emits one of a closed set of typed intents; the frontend renders them. This
 * file is the only place that knows the wire shape, and it is a *mirror*, not a second
 * source of truth: `src/divya/runtime/intents.py` is authoritative and a test asserts the
 * two stay in step.
 *
 * The union is closed on purpose. A language model that emitted arbitrary component names
 * would put a prompt-injection vector between a filing and the screen. It cannot do that
 * here, and this file is the reason it cannot.
 */

export const WORKSPACE_KINDS = [
  "market",
  "company",
  "comparison",
  "screen",
  "event",
  "document",
  "investigation",
  "decision_trace",
  "evidence",
  "alerts",
  "empty",
] as const;

export type WorkspaceKind = (typeof WORKSPACE_KINDS)[number];

export interface UIIntent {
  kind: WorkspaceKind;
  title: string;
  reason: string;
  payload: Record<string, unknown>;
  route: string | null;
  partial: boolean;
  note: string;
}

export interface Workspace {
  task_id: string;
  intents: UIIntent[];
  suggested_next: string[];
  degraded: string[];
  data_freshness: Record<string, string>;
}

export interface Entity {
  kind: string;
  key: string;
  label: string;
  resolved_by: string;
  confidence: number;
}

export interface Turn {
  index: number;
  said: string;
  understood_as: string;
  resolved_entities: Entity[];
  followed_up: boolean;
  notes: string[];
  at: string;
}

export interface Session {
  task_id: string;
  created_at: string;
  updated_at: string;
  objective: string;
  task_type: string;
  turns: Turn[];
  entities: Entity[];
  dimensions: string[];
  decisions: Record<string, unknown>;
  workspace: UIIntent[];
  unresolved: string[];
  degraded: string[];
  suggested_next: string[];
  status: string;
}

export interface CommandResponse {
  task_id: string;
  turn_index: number;
  understood_as: string;
  followed_up: boolean;
  resolved_entities: Entity[];
  workspace: Workspace;
  session: Session;
  degraded: string[];
}

export interface Health {
  status: string;
  version: string;
  system1: string;
  db: string;
  store: Record<string, number>;
}

export interface EventRow {
  seq_id: string;
  symbol: string;
  company: string;
  industry: string;
  nse_desc: string;
  label_event_type: string;
  announced_at: string | null;
  retrieved_at: string;
  is_simulated: boolean;
  pdf_url: string | null;
  text_excerpt?: string;
  decision?: EventDecision | null;
}

export interface EventDecision {
  event_type: string | null;
  event_type_confidence: number | null;
  is_material_p: number | null;
  run_id: string | null;
  spec: string | null;
}

export interface StreamResponse {
  as_of: string | null;
  events: EventRow[];
}

export interface SessionSummary {
  task_id: string;
  objective: string;
  task_type: string;
  turns: number;
  status: string;
  updated_at: string;
  symbols: string[];
}

/** A freshness string is always present, even when it says "no data". */
export function freshnessOf(workspace: Workspace | null): string {
  if (!workspace) return "unknown";
  const first = Object.values(workspace.data_freshness)[0];
  return first ?? "unknown";
}

/**
 * Whether data looks stale, from the freshness string alone.
 *
 * The frontend must never render a number without also signalling staleness, and it must not
 * have to reimplement the backend's window to do that. Anything that is not an explicit
 * "no data" or a recent timestamp is treated as not-fresh, which fails toward caution.
 */
export function isStale(freshness: string): boolean {
  const s = freshness.toLowerCase();
  if (s.includes("no data")) return true;
  const m = s.match(/last retrieved\s+(\S+)/);
  if (!m) return true;
  const ts = Date.parse(m[1]);
  if (Number.isNaN(ts)) return true;
  return Date.now() - ts > 7 * 24 * 3600 * 1000;
}
