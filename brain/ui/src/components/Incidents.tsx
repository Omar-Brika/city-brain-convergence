import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { Incident } from "@/lib/types";

const SEV: Record<string, "destructive" | "warn" | "secondary"> = { critical: "destructive", high: "destructive", medium: "warn", low: "secondary" };

export function Incidents({ incidents }: { incidents: Incident[] }) {
  return (
    <Card className="flex min-h-0 flex-col overflow-hidden">
      <CardHeader className="border-b"><CardTitle className="text-base">Incidents</CardTitle></CardHeader>
      <ScrollArea className="min-h-0 flex-1">
        <CardContent className="space-y-2 p-3">
          {incidents.length === 0 && <div className="py-6 text-center text-sm text-muted-foreground">No incident</div>}
          {incidents.map((i) => {
            const closed = i.status === "closed";
            const c = i.confidence == null ? 0 : Math.round(i.confidence * 100);
            return (
              <div key={i.incident_id} className={cn("rounded-lg border bg-secondary/40 p-3", closed && "opacity-50")}>
                <div className="flex items-center gap-2">
                  <span className="font-semibold capitalize">{(i.type || "").replace("_", " ")}</span>
                  <span className="text-sm text-muted-foreground">{i.zone_name || i.zone_id}</span>
                  <Badge variant={closed ? "ok" : SEV[i.severity || ""] || "secondary"} className="ml-auto capitalize">{closed ? "closed" : i.severity}</Badge>
                </div>
                <Progress value={c} className="my-2" indicatorClassName={closed ? "bg-ok" : "bg-primary"} />
                <div className="flex flex-wrap gap-x-4 text-xs text-muted-foreground">
                  <span>confidence {c}%</span><span>{i.evidence_n || 0} evidence</span>
                  <span className={i.verified === false ? "text-warn" : "text-ok"}>{i.verified === false ? "Unverified (Guardian offline)" : "Verified"}</span>
                  <span className="font-mono">{i.incident_id}</span>
                </div>
              </div>
            );
          })}
        </CardContent>
      </ScrollArea>
    </Card>
  );
}
