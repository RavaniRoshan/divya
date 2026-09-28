"use client";

/**
 * The market workspace: a ranked, dense event stream.
 *
 * **On the component choice.** Space UI's registry also ships a composite `data-grid`
 * (sticky headers, column resize/pin, server pagination). It is not used here, and the reason
 * is worth recording rather than hiding: `components-spaceui-data-grid` depends on
 * `@tanstack/react-table`, and the version the registry resolves to is **v9**, which is a full
 * rewrite — `useTable` instead of `useReactTable`, feature-based `createColumnHelper`, and
 * `flexRender` instead of `columnDef.cell(context)`. Writing a correct integration against a
 * table API this project has not verified would mean shipping code nobody could check.
 *
 * So the event stream is built on Space UI's own `table` primitive, which is a verified
 * component in the same design system. For a 200-row event feed rendered client-side, it
 * gives everything the view actually needs: a sticky header, tabular numerals, dense rows and
 * a hover affordance. The cost is column resize and server pagination, which matter at
 * Bloomberg-terminal row counts and not yet here. If they start to, the grid is the right
 * answer and the v9 API is the work to budget.
 *
 * **Ranking is the decision, not a sort.** Rows are ordered by System-1's `is_material`
 * probability where a decision exists, and undecided events sort *last*. An event the system
 * has not judged is not top priority; it is unjudged, and showing it as if it were would be
 * the single most misleading thing this view could do.
 */

import * as React from "react";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { EventRow, UIIntent } from "@/lib/divya-types";

type SortKey = "symbol" | "material" | "announced";

function MaterialityCell({ p }: { p: number | null | undefined }) {
  if (p === null || p === undefined) {
    return (
      <Tooltip>
        <TooltipTrigger render={<Badge variant="secondary" />}>undecided</TooltipTrigger>
        <TooltipContent>
          No decision on this event yet. It is ranked last, not first.
        </TooltipContent>
      </Tooltip>
    );
  }
  // Bands, not a gradient. Three states is what a decision is worth at this resolution; a
  // continuous colour ramp on a miscalibrated number is decoration pretending to be precision.
  const variant = p >= 0.75 ? "success" : p >= 0.5 ? "warning" : "error";
  return (
    <Tooltip>
      <TooltipTrigger render={<Badge variant={variant} />}>{(p * 100).toFixed(0)}%</TooltipTrigger>
      <TooltipContent>
        System-1 P(material) = {p.toFixed(3)} — raw output. Measured ECE on real filings is
        0.18; the 0.5–0.73 band is specifically uncalibrated.
      </TooltipContent>
    </Tooltip>
  );
}

function System1Cell({ row }: { row: EventRow }) {
  const d = row.decision;
  if (!d?.event_type) {
    return <span className="text-[11px] text-muted-foreground/50">—</span>;
  }
  return (
    <Tooltip>
      <TooltipTrigger
        render={<span className="cursor-help font-mono text-[11px] text-muted-foreground" />}
      >
        {d.event_type}
        {d.event_type_confidence !== null ? ` ${d.event_type_confidence.toFixed(2)}` : ""}
      </TooltipTrigger>
      <TooltipContent>
        <div>raw System-1 output · {d.spec ?? "?"}</div>
        <div>run {d.run_id ?? "?"}</div>
      </TooltipContent>
    </Tooltip>
  );
}

export function MarketWorkspace({
  intent,
  onSelect,
}: {
  intent: UIIntent;
  onSelect?: (row: EventRow) => void;
}) {
  const rows = React.useMemo(() => {
    const raw = ((intent.payload.events ?? []) as EventRow[]).slice();
    return raw.sort((a, b) => {
      const pa = a.decision?.is_material_p;
      const pb = b.decision?.is_material_p;
      if (pa === null || pa === undefined) return pb === null || pb === undefined ? 0 : 1;
      if (pb === null || pb === undefined) return -1;
      return pb - pa;
    });
  }, [intent.payload.events]);

  const [sort, setSort] = React.useState<{ key: SortKey; dir: 1 | -1 }>({
    key: "material",
    dir: -1,
  });

  const sorted = React.useMemo(() => {
    const out = [...rows];
    if (sort.key === "symbol") return out.sort((a, b) => a.symbol.localeCompare(b.symbol) * sort.dir);
    if (sort.key === "announced") {
      return out.sort((a, b) => (a.announced_at ?? "").localeCompare(b.announced_at ?? "") * sort.dir);
    }
    return out;
  }, [rows, sort]);

  function toggle(key: SortKey) {
    setSort((s) => ({ key, dir: s.key === key && s.dir === -1 ? 1 : -1 }));
  }

  const arrow = (k: SortKey) => (sort.key === k ? (sort.dir === -1 ? " ▾" : " ▴") : "");

  if (!rows.length) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center text-[13px] text-muted-foreground">
        {intent.note || "No events in the store. Run `divya index`."}
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto">
      <Table className="text-[12px]">
        <TableHeader className="sticky top-0 z-10 bg-muted/95 backdrop-blur-sm">
          <TableRow className="hover:bg-transparent">
            <TableHead
              className="w-[96px] cursor-pointer select-none text-[11px] uppercase tracking-wide"
              onClick={() => toggle("symbol")}
            >
              sym{arrow("symbol")}
            </TableHead>
            <TableHead className="text-[11px] uppercase tracking-wide">company</TableHead>
            <TableHead className="w-[150px] text-[11px] uppercase tracking-wide">our label</TableHead>
            <TableHead className="hidden w-[190px] text-[11px] uppercase tracking-wide md:table-cell">
              NSE class
            </TableHead>
            <TableHead
              className="w-[104px] cursor-pointer select-none text-[11px] uppercase tracking-wide"
              onClick={() => toggle("material")}
            >
              material{arrow("material")}
            </TableHead>
            <TableHead className="w-[150px] text-[11px] uppercase tracking-wide">System-1</TableHead>
            <TableHead
              className="w-[124px] cursor-pointer select-none text-[11px] uppercase tracking-wide"
              onClick={() => toggle("announced")}
            >
              announced{arrow("announced")}
            </TableHead>
            <TableHead className="w-[46px] text-[11px] uppercase tracking-wide">src</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((r) => (
            <TableRow
              key={r.seq_id}
              onClick={() => onSelect?.(r)}
              className="cursor-pointer border-border/30 hover:bg-accent/40"
            >
              <TableCell className="font-mono text-[12px] font-medium">{r.symbol}</TableCell>
              <TableCell className="max-w-0 truncate">
                <span className="block truncate">{r.company}</span>
              </TableCell>
              <TableCell>
                <Badge
                  variant={r.label_event_type === "unresolved" ? "outline" : "secondary"}
                  className="font-mono text-[10px]"
                >
                  {r.label_event_type}
                </Badge>
              </TableCell>
              <TableCell className="hidden max-w-0 truncate text-[11px] text-muted-foreground md:table-cell">
                <span className="block truncate">{r.nse_desc}</span>
              </TableCell>
              <TableCell>
                <MaterialityCell p={r.decision?.is_material_p} />
              </TableCell>
              <TableCell>
                <System1Cell row={r} />
              </TableCell>
              <TableCell className="font-mono text-[11px] text-muted-foreground">
                {(r.announced_at ?? "—").replace("T", " ").slice(0, 16)}
              </TableCell>
              <TableCell>
                {r.pdf_url ? (
                  <a
                    href={r.pdf_url}
                    target="_blank"
                    rel="noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    className="text-[11px] text-primary underline underline-offset-2"
                  >
                    pdf
                  </a>
                ) : (
                  <span className="text-[11px] text-muted-foreground/40">—</span>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
