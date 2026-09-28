"use client";

/**
 * The non-market workspaces.
 *
 * All of them follow the same contract, and it is the contract that matters: **no view renders
 * a number without also showing where it came from and when it was retrieved.** A market
 * terminal's core failure mode is a confident-looking number with no visible age, and that is
 * an information-design problem before it is a data problem.
 *
 * Each is deliberately a real component rather than a generic JSON dump. A workspace the user
 * can read is the product; a workspace that renders an arbitrary payload is a debugging tool.
 */

import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { UIIntent } from "@/lib/divya-types";
import { MarketWorkspace } from "./MarketWorkspace";
import { isStale } from "@/lib/divya-types";

/** The provenance footer every data-bearing view carries. */
function Freshness({ workspace, note }: { workspace: string; note?: string }) {
  const stale = isStale(workspace);
  return (
    <div className="flex items-center gap-2 border-t border-border/50 px-3 py-1.5 text-[11px] text-muted-foreground">
      <span
        aria-hidden
        className={`inline-block size-1.5 rounded-full ${stale ? "bg-destructive" : "bg-success"}`}
      />
      <span className="font-mono">{workspace}</span>
      {note ? <span className="truncate">· {note}</span> : null}
    </div>
  );
}

function EmptyNote({ intent }: { intent: UIIntent }) {
  return (
    <div className="flex h-full items-center justify-center p-8">
      <div className="max-w-md text-center">
        <p className="text-[13px] text-foreground">{intent.title}</p>
        <p className="mt-1 text-[13px] text-muted-foreground">{intent.note}</p>
        {intent.reason ? (
          <p className="mt-2 text-[11px] text-muted-foreground/70">reason: {intent.reason}</p>
        ) : null}
      </div>
    </div>
  );
}

export function EmptyWorkspace({ intent }: { intent: UIIntent }) {
  return <EmptyNote intent={intent} />;
}

/* ------------------------------------------------------------------ company */

export function CompanyWorkspace({
  intent,
  freshness,
}: {
  intent: UIIntent;
  freshness: string;
}) {
  const { symbol, company, history, decision, as_of } = intent.payload as {
    symbol: string;
    company: string;
    history: Array<Record<string, unknown>>;
    decision?: Record<string, unknown>;
    as_of?: string;
  };
  const rows = (history ?? []) as Array<{
    seq_id: string;
    nse_desc: string;
    label_event_type: string;
    announced_at: string | null;
    decision?: { event_type?: { value?: string; confidence?: number } } | null;
  }>;

  if (!rows?.length) return <EmptyNote intent={intent} />;

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-baseline gap-3 border-b border-border/50 px-3 py-2">
        <h2 className="font-mono text-[15px] font-semibold">{symbol}</h2>
        <span className="text-[13px]">{company}</span>
        {intent.partial ? (
          <Badge variant="warning" className="text-[11px]">
            partial
          </Badge>
        ) : null}
        <Badge variant="outline" className="font-mono text-[11px]">
          {rows.length} filing{rows.length === 1 ? "" : "s"}
        </Badge>
        {as_of ? (
          <span className="ml-auto font-mono text-[11px] text-muted-foreground">
            as of {as_of.replace("T", " ").slice(0, 16)}
          </span>
        ) : null}
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <ul className="divide-y divide-border/40">
          {rows.map((r) => {
            const et = r.decision?.event_type;
            return (
              <li key={r.seq_id} className="flex items-baseline gap-3 px-3 py-1.5">
                <span className="w-[110px] shrink-0 font-mono text-[11px] text-muted-foreground">
                  {(r.announced_at ?? "—").replace("T", " ").slice(0, 16)}
                </span>
                <span className="min-w-0 flex-1 truncate text-[13px]">{r.nse_desc}</span>
                <Badge variant="outline" className="shrink-0 font-mono text-[11px]">
                  {r.label_event_type}
                </Badge>
                {et?.value ? (
                  <Tooltip>
                    <TooltipTrigger
                      render={<Badge variant="secondary" className="shrink-0 font-mono text-[11px]" />}
                    >
                      {et.value}
                      {typeof et.confidence === "number" ? ` ${et.confidence.toFixed(2)}` : ""}
                    </TooltipTrigger>
                    <TooltipContent>raw System-1 output, unaltered</TooltipContent>
                  </Tooltip>
                ) : (
                  <Badge variant="secondary" className="shrink-0 text-[11px]">
                    undecided
                  </Badge>
                )}
              </li>
            );
          })}
        </ul>
      </ScrollArea>
      <Freshness workspace={freshness} note="company workspace" />
    </div>
  );
}

/* -------------------------------------------------------------- comparison */

export function ComparisonWorkspace({
  intent,
  freshness,
}: {
  intent: UIIntent;
  freshness: string;
}) {
  const { entities, dimensions } = intent.payload as {
    entities: Array<{
      symbol: string;
      n_events: number;
      history: Array<{ label_event_type: string; nse_desc: string }>;
    }>;
    dimensions: string[];
  };
  if (!entities?.length) return <EmptyNote intent={intent} />;

  // Cross-tabulate the two sides on the same event types. A comparison is only useful if the
  // rows line up; raw per-entity lists force the user to do the alignment by eye.
  const types = new Set<string>();
  for (const e of entities) for (const h of e.history) types.add(h.label_event_type);
  const rows = [...types].sort();

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-border/50 px-3 py-2">
        <span className="text-[13px] font-medium">{intent.title}</span>
        <span className="text-[11px] text-muted-foreground">
          dimensions: {(dimensions ?? []).join(", ")}
        </span>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <table className="w-full border-collapse text-[13px]">
          <thead className="sticky top-0 bg-muted/60">
            <tr>
              <th className="border-b px-3 py-1.5 text-left text-[11px] font-semibold uppercase text-muted-foreground">
                event type
              </th>
              {entities.map((e) => (
                <th
                  key={e.symbol}
                  className="border-b px-3 py-1.5 text-left text-[11px] font-semibold uppercase text-muted-foreground"
                >
                  <span className="font-mono">{e.symbol}</span>
                  <span className="ml-1 font-normal normal-case">({e.n_events})</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t} className="border-b border-border/30 hover:bg-accent/30">
                <td className="px-3 py-1 font-mono text-[12px] text-muted-foreground">{t}</td>
                {entities.map((e) => {
                  const n = e.history.filter((h) => h.label_event_type === t).length;
                  return (
                    <td key={e.symbol} className="px-3 py-1 font-mono text-[12px]">
                      {n > 0 ? n : <span className="text-muted-foreground/40">—</span>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollArea>
      <Freshness workspace={freshness} note="comparison workspace" />
    </div>
  );
}

/* ------------------------------------------------------------------ screen */

export function ScreenWorkspace({
  intent,
  freshness,
}: {
  intent: UIIntent;
  freshness: string;
}) {
  const { rows, predicate } = intent.payload as {
    rows: Array<{
      symbol: string;
      company: string;
      label_event_type: string;
      nse_desc: string;
      announced_at: string | null;
    }>;
    predicate: string;
  };
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-border/50 px-3 py-2">
        <span className="text-[13px] font-medium">Screen</span>
        <span className="font-mono text-[11px] text-muted-foreground">{predicate}</span>
        <Badge variant="secondary" className="ml-auto font-mono text-[11px]">
          {rows?.length ?? 0} rows
        </Badge>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        {intent.partial && !rows?.length ? (
          <EmptyNote intent={intent} />
        ) : (
          <ul className="divide-y divide-border/40">
            {rows.map((r, i) => (
              <li key={`${r.symbol}-${i}`} className="flex items-baseline gap-3 px-3 py-1.5">
                <span className="w-[90px] shrink-0 font-mono text-[12px] font-medium">
                  {r.symbol}
                </span>
                <span className="min-w-0 flex-1 truncate text-[13px]">{r.company}</span>
                <span className="hidden shrink-0 text-[12px] text-muted-foreground md:inline">
                  {r.nse_desc}
                </span>
                <Badge variant="outline" className="shrink-0 font-mono text-[11px]">
                  {r.label_event_type}
                </Badge>
              </li>
            ))}
          </ul>
        )}
      </ScrollArea>
      <Freshness workspace={freshness} note="screen" />
    </div>
  );
}

/* ---------------------------------------------------------------- evidence */

export function EvidenceWorkspace({
  intent,
  freshness,
}: {
  intent: UIIntent;
  freshness: string;
}) {
  const { sources, claim } = intent.payload as {
    sources: Array<{
      symbol: string;
      seq_id: string;
      source_id: string;
      url: string | null;
      announced_at: string | null;
      retrieved_at: string;
      excerpt: string;
      decision_made: string | null;
    }>;
    claim: string;
  };
  if (!sources?.length) return <EmptyNote intent={intent} />;

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border/50 px-3 py-2">
        <span className="text-[13px] font-medium">Evidence</span>
        {claim ? (
          <p className="mt-0.5 text-[12px] text-muted-foreground">for: {claim}</p>
        ) : null}
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <ul className="divide-y divide-border/40">
          {sources.map((s) => (
            <li key={s.seq_id} className="px-3 py-2">
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-[12px] font-medium">{s.symbol}</span>
                <span className="font-mono text-[11px] text-muted-foreground">{s.source_id}</span>
                <span className="ml-auto font-mono text-[11px] text-muted-foreground">
                  {(s.announced_at ?? "—").replace("T", " ").slice(0, 16)}
                </span>
                {s.url ? (
                  <a
                    href={s.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-[11px] text-primary underline underline-offset-2"
                  >
                    source
                  </a>
                ) : null}
              </div>
              <p className="mt-1 line-clamp-3 text-[12px] leading-relaxed text-muted-foreground">
                {s.excerpt}
              </p>
              {s.decision_made ? (
                <p className="mt-1 font-mono text-[11px] text-muted-foreground/80">
                  decision on this document: {s.decision_made}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      </ScrollArea>
      <Freshness workspace={freshness} note="evidence" />
    </div>
  );
}

/* ----------------------------------------------------------- investigation */

export function InvestigationWorkspace({
  intent,
  freshness,
}: {
  intent: UIIntent;
  freshness: string;
}) {
  const { steps, status } = intent.payload as {
    steps: Array<{ turn: number; said: string; at: string }>;
    status: string;
  };
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-border/50 px-3 py-2">
        <h2 className="text-[13px] font-semibold">{intent.title}</h2>
        <Badge variant={status === "active" ? "info" : "secondary"} className="text-[11px]">
          {status}
        </Badge>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <ol className="px-3 py-2">
          {(steps ?? []).map((s, i) => (
            <li key={i} className="relative border-l border-border/60 pb-3 pl-4">
              <span className="absolute -left-[3px] top-1 size-1.5 rounded-full bg-primary" />
              <div className="text-[13px]">{s.said}</div>
              <div className="font-mono text-[11px] text-muted-foreground">{s.at}</div>
            </li>
          ))}
        </ol>
      </ScrollArea>
      <Freshness workspace={freshness} note="investigation" />
    </div>
  );
}

/* ------------------------------------------------------------------ router */

export function WorkspaceRegion({ intents, freshness }: { intents: UIIntent[]; freshness: string }) {
  const first = intents[0];
  if (!first) return null;

  // Workspaces that draw their own header (they have a richer one than reason + title) opt out
  // of the region header rather than having their title printed twice.
  const selfHeader = first.kind === "investigation" || first.kind === "company";

  const body = (() => {
    switch (first.kind) {
      case "market":
        return <MarketWorkspace intent={first} />;
      case "company":
        return <CompanyWorkspace intent={first} freshness={freshness} />;
      case "comparison":
        return <ComparisonWorkspace intent={first} freshness={freshness} />;
      case "screen":
        return <ScreenWorkspace intent={first} freshness={freshness} />;
      case "evidence":
        return <EvidenceWorkspace intent={first} freshness={freshness} />;
      case "investigation":
        return <InvestigationWorkspace intent={first} freshness={freshness} />;
      default:
        return <EmptyNote intent={first} />;
    }
  })();

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {selfHeader ? null : (
        <div className="flex items-baseline gap-2 border-b border-border/60 px-3 py-2">
          <h2 className="text-[13px] font-semibold">{first.title || "Workspace"}</h2>
          {first.reason ? (
            <span className="text-[12px] text-muted-foreground">{first.reason}</span>
          ) : null}
          {first.partial ? (
            <Badge variant="warning" className="text-[11px]">
              partial
            </Badge>
          ) : null}
        </div>
      )}
      <div className="min-h-0 flex-1">{body}</div>
      {intents.length > 1 ? (
        <>
          <Separator />
          <div className="max-h-40 overflow-y-auto px-3 py-2">
            {intents.slice(1).map((i) => (
              <div key={i.kind} className="mb-2 text-[12px]">
                <span className="font-semibold">{i.title}</span>
                <span className="ml-2 text-muted-foreground">{i.note || i.reason}</span>
              </div>
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}
