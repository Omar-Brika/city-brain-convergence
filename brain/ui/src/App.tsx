import { useEffect, useState } from "react";
import { ChainDialog } from "@/components/ChainDialog";
import { CityMap } from "@/components/CityMap";
import { DecisionCard } from "@/components/DecisionCard";
import { Header } from "@/components/Header";
import { Incidents } from "@/components/Incidents";
import { StatsStrip } from "@/components/StatsStrip";
import { Timeline } from "@/components/Timeline";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useTimeline } from "@/hooks/useTimeline";
import { cn } from "@/lib/utils";

const KEY = "cb-mapfocus";

export default function App() {
  const { rows, state, connected, loadChain, localChain } = useTimeline();
  const [chain, setChain] = useState<string | null>(null);
  const [focusMap, setFocusMap] = useState(() => { try { return localStorage.getItem(KEY) !== "0"; } catch { return true; } });

  useEffect(() => { try { localStorage.setItem(KEY, focusMap ? "1" : "0"); } catch { /* ignore */ } }, [focusMap]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "m" || e.key === "M") setFocusMap((v) => !v);
      if (e.key === "f" || e.key === "F") {
        if (document.fullscreenElement) void document.exitFullscreen(); else void document.documentElement.requestFullscreen().catch(() => {});
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <TooltipProvider delayDuration={150}>
      <div className="flex h-screen flex-col">
        <Header state={state} connected={connected} focusMap={focusMap} onToggleView={() => setFocusMap((v) => !v)} />
        <StatsStrip state={state} />
        <main className={cn("grid min-h-0 flex-1 gap-3 p-3", focusMap ? "grid-cols-[1.5fr_1fr]" : "grid-cols-[1fr_1.7fr]")}>
          <div className="grid min-h-0 grid-rows-[minmax(0,1fr)_13.5rem] gap-3">
            <CityMap state={state} />
            <div className="grid min-h-0 grid-cols-2 gap-3">
              <Incidents incidents={state?.incidents || []} />
              <DecisionCard decision={state?.decision} />
            </div>
          </div>
          <div className="relative flex min-h-0 flex-col"><Timeline rows={rows} onOpenChain={setChain} /></div>
        </main>
        <ChainDialog cid={chain} onClose={() => setChain(null)} loadChain={loadChain} localChain={localChain} />
      </div>
    </TooltipProvider>
  );
}
