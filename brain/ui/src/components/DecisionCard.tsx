import { Check } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { Decision } from "@/lib/types";

export function DecisionCard({ decision: d }: { decision: Decision | null | undefined }) {
  const opts = d ? [{ origin: d.origin, score: d.score, win: true }].concat((d.alternatives || []).map((a) => ({ origin: a.origin, score: a.score, win: false }))) : [];
  const max = Math.max(...opts.map((o) => Number(o.score) || 0), 1e-9);
  return (
    <Card className="flex min-h-0 flex-col overflow-hidden">
      <CardHeader className="border-b"><CardTitle className="text-base">Last decision</CardTitle></CardHeader>
      <ScrollArea className="min-h-0 flex-1">
        <CardContent className="p-3">
          {!d ? <div className="py-6 text-center text-sm text-muted-foreground">No decision yet</div> : (
            <>
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <Badge variant="outline" className={cn(d.origin === "llm" ? "text-llm" : "text-brain")}>{(d.origin || "?").toUpperCase()}</Badge>
                <span className="font-mono">{d.id}</span><span className="font-mono">{d.incident_id}</span>
                {d.mode === "safe" && <Badge variant="warn">Safe mode</Badge>}
                <span>risk {d.risk || "-"}</span>
              </div>
              <div className="my-2 flex flex-wrap gap-1.5">
                {(d.actions || []).length ? d.actions!.map((a) => (
                  <span key={a} className="rounded-md border bg-secondary px-2 py-0.5 font-mono text-sm">{a}</span>
                )) : <span className="text-sm text-muted-foreground">no action</span>}
              </div>
              {opts.map((o, i) => (
                <div key={i} className={cn("my-1 grid grid-cols-[5.5rem_1fr_3rem] items-center gap-3 text-sm", o.win && "font-semibold")}>
                  <span className="flex items-center gap-1">{(o.origin || "?").toUpperCase()}{o.win && <Check className="h-3.5 w-3.5 text-ok" />}</span>
                  <div className="h-2 rounded-sm bg-secondary">
                    <div className={cn("h-full rounded-sm", o.win ? "bg-ok" : "bg-muted-foreground/40")} style={{ width: `${Math.max(4, ((Number(o.score) || 0) / max) * 100)}%` }} />
                  </div>
                  <span className="text-right font-mono">{(Number(o.score) || 0).toFixed(2)}</span>
                </div>
              ))}
              {d.explanation && <p className="mt-2 text-sm text-muted-foreground">{d.explanation}</p>}
            </>
          )}
        </CardContent>
      </ScrollArea>
    </Card>
  );
}
