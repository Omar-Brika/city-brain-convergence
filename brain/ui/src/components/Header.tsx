import { useEffect, useState } from "react";
import { LayoutPanelLeft } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { fmtTime, pad } from "@/lib/format";
import type { State } from "@/lib/types";

const LAYER_NAMES: [string, string][] = [["twin", "Twin"], ["guardian", "Guardian"], ["brain", "Brain"], ["llm", "LLM"]];

function LayerStatus({ name, status, reason }: { name: string; status: string; reason?: string }) {
  const tone = status === "online" ? "bg-ok" : status === "offline" ? "bg-destructive" : status === "degraded" ? "bg-warn" : "bg-muted-foreground/50";
  const text = status === "offline" ? "text-destructive" : status === "degraded" ? "text-warn" : "text-muted-foreground";
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="flex items-center gap-2">
          <span className={cn("h-2 w-2 rounded-full", tone)} />
          <span className="font-medium">{name}</span>
          <span className={cn("text-sm", text)}>{status}</span>
        </div>
      </TooltipTrigger>
      <TooltipContent>{reason || `${name} is ${status}`}</TooltipContent>
    </Tooltip>
  );
}

export function Header({ state, connected, focusMap, onToggleView }: {
  state: State | null; connected: boolean; focusMap: boolean; onToggleView: () => void;
}) {
  const [now, setNow] = useState(new Date());
  useEffect(() => { const t = setInterval(() => setNow(new Date()), 250); return () => clearInterval(t); }, []);
  const layers = state?.layers || {};
  const run = state?.run;
  const secs = run?.started ? Math.max(0, Math.round((now.getTime() - new Date(run.started).getTime()) / 1000)) : 0;
  return (
    <header className="flex items-center gap-8 border-b px-5 py-3">
      <div className="leading-tight">
        <div className="text-xl font-semibold tracking-tight">City Brain</div>
        <div className="text-xs text-muted-foreground">Live timeline · Twin → Guardian → Brain</div>
      </div>
      <div className="flex items-center gap-6 text-base">
        {LAYER_NAMES.map(([id, name]) => (
          <LayerStatus key={id} name={name} status={layers[id]?.status || "unknown"} reason={layers[id]?.reason} />
        ))}
      </div>
      {state?.safe_mode && <Badge variant="warn" className="px-3 py-1 text-sm">Safe mode</Badge>}
      {!connected && <Badge variant="destructive">Connection lost, reconnecting…</Badge>}
      <div className="flex-1" />
      <Button variant="ghost" size="sm" onClick={onToggleView} title="Switch the focus between the city map and the timeline (key M)">
        <LayoutPanelLeft /> {focusMap ? "Timeline view" : "Map view"} <kbd className="ml-1 rounded border px-1 font-mono text-[10px] text-muted-foreground">M</kbd>
      </Button>
      <div className="text-right leading-tight">
        <div className={cn("text-sm font-semibold", run ? "text-ok" : "text-muted-foreground")}>
          {run ? `Scenario ${run.scenario_id || "?"} · ${pad(Math.floor(secs / 60))}:${pad(secs % 60)}` : "Live · no scenario run"}
        </div>
        {state?.log_file && <div className="font-mono text-[11px] text-muted-foreground">logs/{state.log_file}</div>}
      </div>
      <div className="min-w-[7.5ch] text-right font-mono text-2xl font-medium">{fmtTime(now)[0]}</div>
    </header>
  );
}
