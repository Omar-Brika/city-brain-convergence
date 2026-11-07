import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import type { State } from "@/lib/types";

type Tone = "none" | "bad" | "warn" | "good";

function Stat({ value, label, tone = "none", always = false }: { value: number; label: string; tone?: Tone; always?: boolean }) {
  // zero fades out, so only the numbers that matter stand out
  const colour = value === 0 && !always ? "text-muted-foreground/50"
    : tone === "bad" ? "text-destructive" : tone === "warn" ? "text-warn" : tone === "good" ? "text-ok" : "text-foreground";
  return (
    <div className="flex flex-1 items-baseline gap-2.5 px-4 first:pl-0">
      <span className={cn("font-mono text-2xl", colour)}>{value}</span>
      <span className="text-sm text-muted-foreground">{label}</span>
    </div>
  );
}

export function StatsStrip({ state }: { state: State | null }) {
  const c = state?.counters || {};
  const open = (state?.incidents || []).filter((i) => i.status !== "closed").length;
  const items: [number, string, Tone, boolean][] = [
    [c.msgs_per_s ?? 0, "msg/s", "none", true], [c.sent ?? 0, "commands sent", "none", true],
    [c.acked ?? 0, "acknowledged", "good", false], [c.refused ?? 0, "refused", "bad", false],
    [c.failed ?? 0, "failed", "bad", false], [c.alerts ?? 0, "alerts", "warn", false],
    [c.errors ?? 0, "rejected input", "warn", false], [open, "open incidents", "none", true],
  ];
  return (
    <section className="flex items-center border-b px-5 py-2">
      {items.flatMap(([v, l, t, a], i) => [
        i > 0 ? <Separator key={"s" + i} orientation="vertical" className="h-6" /> : null,
        <Stat key={l} value={v} label={l} tone={t} always={a} />,
      ])}
    </section>
  );
}
