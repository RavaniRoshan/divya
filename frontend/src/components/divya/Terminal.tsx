"use client";

/**
 * The Divya terminal shell.
 *
 * Layout is the product's information architecture, decided once here:
 *
 *   ┌─────────────────────────────────────────────────────────────┐
 *   │ command surface — always visible, `/` to focus               │  control layer
 *   ├──────────┬────────────────────────────────┬─────────────────┤
 *   │ context  │ workspace                     │ evidence rail   │  analytical
 *   │ rail     │ (from the typed UI intent)    │ (sources, conf) │  surface
 *   ├──────────┴────────────────────────────────┴─────────────────┤
 *   │ status: freshness · engine · model · degradation            │  provenance
 *   └─────────────────────────────────────────────────────────────┘
 *
 * The context rail is persistent on the left, the evidence rail on the right, and the
 * workspace in the middle. That is a terminal's information architecture, not a generic
 * three-column dashboard: the left is *what I am working on*, the middle is *the answer*,
 * the right is *why I should believe it*.
 */

import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { CommandSurface } from "./CommandSurface";
import { WorkspaceRegion } from "./workspaces";
import { ApiError, api } from "@/lib/api";
import type { Health, Session, SessionSummary, Workspace } from "@/lib/divya-types";
import { isStale } from "@/lib/divya-types";

function Rail({
  title,
  children,
  className,
}: {
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex min-h-0 flex-col", className)}>
      <div className="border-b border-border/50 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </div>
      <ScrollArea className="min-h-0 flex-1">{children}</ScrollArea>
    </div>
  );
}

function cn(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

export function Terminal() {
  const [taskId, setTaskId] = React.useState<string | null>(null);
  const [workspace, setWorkspace] = React.useState<Workspace | null>(null);
  const [session, setSession] = React.useState<Session | null>(null);
  const [sessions, setSessions] = React.useState<SessionSummary[]>([]);
  const [health, setHealth] = React.useState<Health | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  const loadSessions = React.useCallback(async () => {
    try {
      setSessions((await api.sessions()).sessions);
    } catch {
      /* the rail is not worth an error banner; health already reports the backend */
    }
  }, []);

  React.useEffect(() => {
    void (async () => {
      try {
        setHealth(await api.health());
      } catch (e) {
        setError(
          e instanceof ApiError ? e.message : "backend unreachable — start it with `divya serve`",
        );
      }
      await loadSessions();
    })();
  }, [loadSessions]);

  const onResult = React.useCallback(
    (r: { workspace: Workspace; session: Session }) => {
      setWorkspace(r.workspace);
      setSession(r.session);
      setTaskId(r.session.task_id);
      setError(null);
      void loadSessions();
    },
    [loadSessions],
  );

  const onError = React.useCallback((m: string) => setError(m), []);

  const degraded = React.useMemo(() => {
    const out = [...(workspace?.degraded ?? [])];
    if (error) out.unshift(error);
    if (health && health.system1 !== "laya") {
      out.push("system1: engine unavailable; no typed decisions can be produced");
    }
    return out;
  }, [workspace, error, health]);

  const freshness = Object.values(workspace?.data_freshness ?? {})[0] ?? "no data ingested";
  const stale = isStale(freshness);
  const decisions = Object.keys(session?.decisions ?? {});

  async function openSession(id: string) {
    setLoading(true);
    try {
      const [s, w] = await Promise.all([api.session(id), api.workspace(id)]);
      setSession(s);
      setWorkspace(w);
      setTaskId(id);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "could not open that session");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex h-dvh flex-col bg-background text-foreground">
      <CommandSurface
        taskId={taskId}
        onResult={onResult}
        onError={onError}
        degraded={degraded}
      />

      <div className="grid min-h-0 flex-1 grid-cols-[240px_minmax(0,1fr)_300px]">
        <Rail title="context" className="border-r border-border/50">
          <div className="p-2">
            <div className="mb-1 px-1 text-[10px] uppercase tracking-wide text-muted-foreground">
              task
            </div>
            {session ? (
              <div className="rounded-sm border border-border/50 bg-card/40 p-2">
                <div className="truncate text-[12px]">{session.objective || "(no objective)"}</div>
                <div className="mt-1 flex flex-wrap gap-1">
                  <Badge variant="outline" className="text-[10px]">
                    {session.task_type}
                  </Badge>
                  <Badge variant="outline" className="text-[10px]">
                    {session.turns.length} turn{session.turns.length === 1 ? "" : "s"}
                  </Badge>
                  {session.status !== "active" ? (
                    <Badge variant="secondary" className="text-[10px]">
                      {session.status}
                    </Badge>
                  ) : null}
                </div>
                {session.entities.length ? (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {session.entities.map((e) => (
                      <Tooltip key={`${e.kind}-${e.key}`}>
                        <TooltipTrigger render={<Badge variant="secondary" className="font-mono text-[10px]" />}>
                          {e.key}
                        </TooltipTrigger>
                        <TooltipContent>
                          {e.label} · resolved by {e.resolved_by} · confidence {e.confidence}
                        </TooltipContent>
                      </Tooltip>
                    ))}
                  </div>
                ) : null}
                {session.dimensions.length ? (
                  <div className="mt-1.5 text-[11px] text-muted-foreground">
                    narrowed to: <span className="font-mono">{session.dimensions.join(", ")}</span>
                  </div>
                ) : null}
              </div>
            ) : (
              <p className="px-1 py-2 text-[12px] text-muted-foreground">
                No active task. Ask something above.
              </p>
            )}
          </div>

          <Separator />

          <div className="p-2">
            <div className="mb-1 px-1 text-[10px] uppercase tracking-wide text-muted-foreground">
              recent
            </div>
            <ul className="space-y-0.5">
              {sessions.map((s) => (
                <li key={s.task_id}>
                  <button
                    type="button"
                    onClick={() => void openSession(s.task_id)}
                    className={cn(
                      "w-full rounded-sm px-1.5 py-1 text-left text-[12px] hover:bg-accent/50",
                      s.task_id === taskId && "bg-accent/60",
                    )}
                  >
                    <div className="truncate">{s.objective || "(untitled)"}</div>
                    <div className="font-mono text-[10px] text-muted-foreground">
                      {s.task_type} · {s.turns}t{s.symbols.length ? ` · ${s.symbols.join(",")}` : ""}
                    </div>
                  </button>
                </li>
              ))}
              {sessions.length === 0 ? (
                <li className="px-1.5 py-2 text-[12px] text-muted-foreground">No saved tasks.</li>
              ) : null}
            </ul>
          </div>
        </Rail>

        <main className="min-h-0 overflow-hidden border-r border-border/50">
          {workspace ? (
            <WorkspaceRegion intents={workspace.intents} freshness={freshness} />
          ) : (
            <div className="flex h-full items-center justify-center p-8">
              <div className="max-w-lg text-center">
                <p className="text-[13px] text-muted-foreground">
                  Ask what matters. Divya decomposes the task, runs the typed decision engine,
                  and builds the workspace.
                </p>
                <p className="mt-3 text-[12px] text-muted-foreground/70">
                  {loading ? "loading…" : "Start with: “What changed materially today?”"}
                </p>
              </div>
            </div>
          )}
        </main>

        <Rail title="evidence">
          <div className="p-2">
            <div className="mb-1 px-1 text-[10px] uppercase tracking-wide text-muted-foreground">
              decisions on this task
            </div>
            {decisions.length ? (
              <ul className="space-y-0.5">
                {decisions.map((d) => (
                  <li key={d} className="px-1.5 py-0.5 font-mono text-[12px]">
                    {d}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="px-1 py-1.5 text-[12px] text-muted-foreground">
                No decision recorded yet. Decisions are made by the typed engine, not by the
                language model, and are stored with the run that produced them.
              </p>
            )}

            {session?.unresolved.length ? (
              <>
                <Separator className="my-2" />
                <div className="mb-1 px-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                  unresolved
                </div>
                <ul className="space-y-0.5 px-1.5">
                  {session.unresolved.map((u) => (
                    <li key={u} className="text-[12px] text-warning">
                      {u}
                    </li>
                  ))}
                </ul>
              </>
            ) : null}

            {workspace?.suggested_next.length ? (
              <>
                <Separator className="my-2" />
                <div className="mb-1 px-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                  next
                </div>
                <ul className="space-y-0.5">
                  {workspace.suggested_next.map((s) => (
                    <li key={s} className="px-1.5 text-[12px] text-muted-foreground">
                      {s}
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
          </div>
        </Rail>
      </div>

      <div className="flex items-center gap-3 border-t border-border/60 bg-card/40 px-3 py-1 font-mono text-[11px] text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <span className={cn("inline-block size-1.5 rounded-full", stale ? "bg-destructive" : "bg-success")} />
          {freshness}
        </span>
        <span>system1: {health?.system1 ?? "?"}</span>
        <span>db: {health?.store ? `${health.store.events} events` : "?"}</span>
        <span className="ml-auto truncate">{degraded[0] ?? ""}</span>
      </div>
    </div>
  );
}
