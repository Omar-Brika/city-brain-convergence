import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ShieldAlert, ShieldCheck } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/utils";
import { cidColor, fmtTime, layerClass } from "@/lib/format";
import { LAYERS, type Row } from "@/lib/types";

export function Timeline({ rows, onOpenChain }: { rows: Row[]; onOpenChain: (cid: string) => void }) {
  const [visible, setVisible] = useState<string[]>([...LAYERS]);
  const [paused, setPaused] = useState(false);
  const [hoverCid, setHoverCid] = useState<string | null>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const seenWhenPaused = useRef(0);
  const [unseen, setUnseen] = useState(0);
  const lastSeq = rows.length ? rows[rows.length - 1].seq : 0;
  const shown = rows.filter((r) => visible.includes(r.layer));

  // follow the newest row, unless the pointer is on the list (hover = pause, to read)
  useLayoutEffect(() => {
    const el = viewport.current;
    if (el && !paused) el.scrollTop = el.scrollHeight;
  }, [lastSeq, paused, visible]);
  useEffect(() => { if (!paused) { seenWhenPaused.current = lastSeq; setUnseen(0); } else setUnseen(rows.filter((r) => r.seq > seenWhenPaused.current).length); }, [lastSeq, paused, rows]);
  useEffect(() => { if (paused) seenWhenPaused.current = lastSeq; /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [paused]);

  return (
    <Card className="flex min-h-0 flex-col overflow-hidden">
      <CardHeader className="border-b">
        <CardTitle className="text-base">Timeline</CardTitle>
        <Badge variant={paused ? "warn" : "ok"} className="text-[11px]">{paused ? "Paused" : "Live"}</Badge>
        <span className="text-xs text-muted-foreground">Hover to pause · click for the chain</span>
        <ToggleGroup type="multiple" value={visible} onValueChange={setVisible} size="sm" className="ml-auto" aria-label="Layers shown">
          {LAYERS.map((l) => (
            <ToggleGroupItem key={l} value={l} className={cn("h-7 rounded-full px-3 text-xs font-semibold", layerClass[l])}>{l}</ToggleGroupItem>
          ))}
        </ToggleGroup>
      </CardHeader>
      <ScrollArea className="min-h-0 flex-1" viewportRef={viewport}>
        <div onMouseEnter={() => setPaused(true)} onMouseLeave={() => { setPaused(false); setHoverCid(null); }}>
          <Table>
            <TableHeader className="sticky top-0 z-10 bg-card">
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-1 p-0" />
                <TableHead className="w-[7.5rem]">Time</TableHead>
                <TableHead className="w-[6.5rem]">Layer</TableHead>
                <TableHead>Event</TableHead>
                <TableHead className="w-8" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {shown.length === 0 && (
                <TableRow className="hover:bg-transparent"><TableCell colSpan={5} className="py-10 text-center text-muted-foreground">Waiting for events…</TableCell></TableRow>
              )}
              {shown.map((r) => {
                const [t, ms] = fmtTime(r.ts);
                const dim = hoverCid && r.cid !== hoverCid;
                return (
                  <TableRow
                    key={r.seq}
                    onMouseOver={() => setHoverCid(r.cid || null)}
                    onClick={() => r.cid && onOpenChain(r.cid)}
                    title={`${r.topic || ""}${r.cid ? "  |  chain " + r.cid : ""}`}
                    className={cn(
                      "row-new", r.cid && "cursor-pointer", dim && "opacity-35",
                      r.level === "error" && "bg-destructive/10 hover:bg-destructive/15",
                    )}
                  >
                    <TableCell className="w-1 p-0">
                      <div className="h-full min-h-8 w-[3px]" style={{ background: r.level === "error" ? "hsl(var(--destructive))" : cidColor(r.cid) }} />
                    </TableCell>
                    <TableCell className="whitespace-nowrap font-mono text-sm text-muted-foreground">{t}<span className="opacity-60">{ms}</span></TableCell>
                    <TableCell className={cn("text-xs font-semibold tracking-wide", layerClass[r.layer])}>{r.layer}</TableCell>
                    <TableCell className={cn("text-base leading-snug [overflow-wrap:anywhere]",
                      r.level === "error" && "font-medium text-red-200", r.level === "warn" && "text-warn")}>{r.text}</TableCell>
                    <TableCell className="px-2">
                      {r.signed === true ? <ShieldCheck className="h-4 w-4 text-ok/40" />
                        : r.signed === false ? <ShieldAlert className="h-4 w-4 text-destructive" /> : null}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      </ScrollArea>
      {paused && unseen > 0 && (
        <div className="pointer-events-none absolute bottom-3 left-1/2 -translate-x-1/2">
          <Badge variant="warn" className="px-3 py-1">Paused · {unseen} new below</Badge>
        </div>
      )}
    </Card>
  );
}
