import { useEffect, useRef } from "react";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { drawMap, mountMap } from "@/map/city";
import type { State } from "@/lib/types";

export function CityMap({ state }: { state: State | null }) {
  const el = useRef<HTMLDivElement>(null);
  useEffect(() => { if (el.current) mountMap(el.current); }, []);
  useEffect(() => { if (state) drawMap(state); }, [state]);
  return (
    <Card className="flex min-h-0 flex-col overflow-hidden">
      <CardHeader className="border-b">
        <CardTitle className="text-base">City</CardTitle>
        <span className="text-xs text-muted-foreground">Live, as the Brain sees it</span>
      </CardHeader>
      <div ref={el} className="flex min-h-0 flex-1 [&_svg]:h-full [&_svg]:w-full">
        <div className="m-auto text-sm text-muted-foreground">Waiting for the city description…</div>
      </div>
    </Card>
  );
}
