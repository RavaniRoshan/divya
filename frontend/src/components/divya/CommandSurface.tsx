"use client";

/**
 * The command surface: conversation as the primary control layer.
 *
 * This is not a chat window bolted onto a dashboard. It is the *control* layer, and it is
 * always visible, because the product thesis is that the user expresses intent and the system
 * constructs the workspace. A control surface you have to go find is not a control surface.
 *
 * Three behaviours it must get right, each of which was wrong in an earlier version:
 *
 * 1. **Follow-ups are visibly follow-ups.** When the user narrows an existing task the input
 *    shows which task it continues. Without that, "now only asset quality" looks like a fresh
 *    question and the user has no way to know the scope silently changed.
 * 2. **A failed command says why and leaves the workspace intact.** The previous workspace
 *    stays on screen. Losing the context you were reading because a follow-up failed is worse
 *    than the failure.
 * 3. **Degradation is shown, not swallowed.** If the backend is down or System-1 is missing,
 *    the surface says so in plain words. A terminal that quietly shows less than it has is
 *    worse than one that is loudly degraded.
 */

import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Kbd } from "@/components/ui/kbd";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import type { Session, Workspace } from "@/lib/divya-types";
import { ApiError, api } from "@/lib/api";

export interface CommandSurfaceProps {
  taskId: string | null;
  onResult: (r: { workspace: Workspace; session: Session; followedUp: boolean }) => void;
  onError: (message: string) => void;
  degraded: string[];
}

const EXAMPLES = [
  "What changed materially across the market today?",
  "Investigate Infosys.",
  "Why is this high priority?",
  "Show me the evidence.",
];

export function CommandSurface({
  taskId,
  onResult,
  onError,
  degraded,
}: CommandSurfaceProps) {
  const [text, setText] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement>(null);

  // `/` focuses the command line from anywhere. A keyboard-first terminal that requires the
  // mouse to reach its primary control surface is not keyboard-first.
  React.useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      const typing =
        target &&
        (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);
      if (e.key === "/" && !typing) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  async function send(value: string) {
    const utterance = value.trim();
    if (!utterance || busy) return;
    setBusy(true);
    try {
      const r = await api.command(utterance, taskId ?? undefined);
      onResult({ workspace: r.workspace, session: r.session, followedUp: r.followed_up });
      setText("");
    } catch (e) {
      onError(
        e instanceof ApiError
          ? e.message
          : "command failed for an unknown reason",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="border-b border-border/60 bg-card/40">
      <div className="flex items-center gap-2 px-3 py-1.5">
        <span className="font-mono text-[11px] uppercase tracking-wide text-muted-foreground">
          divya
        </span>
        {taskId ? (
          <Badge variant="info" className="font-mono text-[10px]">
            continuing {taskId.slice(0, 11)}
          </Badge>
        ) : (
          <Badge variant="outline" className="font-mono text-[10px]">
            new task
          </Badge>
        )}
        <div className="ml-auto flex items-center gap-1 text-[11px] text-muted-foreground">
          <Kbd>/</Kbd>
          <span>focus</span>
        </div>
      </div>

      <div className="flex items-center gap-2 px-3 pb-2">
        <input
          ref={inputRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void send(text);
            if (e.key === "Escape") inputRef.current?.blur();
          }}
          placeholder={
            taskId
              ? "Ask a follow-up — scope is preserved from the current task"
              : "What changed materially today?  /  Investigate a company  /  Compare two"
          }
          aria-label="Command"
          className={cn(
            "h-8 flex-1 rounded-sm border border-input bg-background px-2 font-mono text-[13px]",
            "outline-none placeholder:text-muted-foreground/60 focus:border-primary",
          )}
        />
        <button
          type="button"
          onClick={() => void send(text)}
          disabled={busy || !text.trim()}
          className="h-8 rounded-sm border border-border px-3 text-[12px] hover:bg-accent disabled:opacity-50"
        >
          {busy ? <Spinner /> : "Run"}
        </button>
      </div>

      {degraded.length > 0 ? (
        <div className="flex items-start gap-2 border-t border-destructive/40 bg-destructive/10 px-3 py-1.5">
          <span className="mt-1 inline-block size-1.5 shrink-0 rounded-full bg-destructive" />
          <div className="min-w-0 text-[11px] text-destructive">
            {degraded.map((d) => (
              <div key={d} className="truncate">
                {d}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {!taskId ? (
        <div className="flex flex-wrap gap-1.5 px-3 pb-2">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => void send(ex)}
              className="rounded-sm border border-border/60 px-2 py-0.5 text-[11px] text-muted-foreground hover:border-primary hover:text-foreground"
            >
              {ex}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
