import type { Temperature } from "./api";

export const money = (value: number) =>
  new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value) + " ₽";

export const compactMoney = (value: number) =>
  value >= 1_000_000
    ? `${(value / 1_000_000).toFixed(1)} млн ₽`
    : value >= 1000
      ? `${Math.round(value / 1000)} тыс ₽`
      : `${value} ₽`;

export function timeOf(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  return date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

export function dateTimeOf(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function dayOf(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("ru-RU", { day: "2-digit", month: "short" });
}

/** Relative label against the demo clock, e.g. "через 12 мин" / "8 мин назад". */
export function relativeTo(iso: string | null | undefined, nowIso: string | undefined): string {
  if (!iso || !nowIso) return "—";
  const delta = (new Date(iso).getTime() - new Date(nowIso).getTime()) / 1000;
  const abs = Math.abs(delta);
  const unit =
    abs < 60
      ? `${Math.round(abs)} с`
      : abs < 3600
        ? `${Math.round(abs / 60)} мин`
        : abs < 86400
          ? `${Math.round(abs / 3600)} ч`
          : `${Math.round(abs / 86400)} дн`;
  return delta >= 0 ? `через ${unit}` : `${unit} назад`;
}

export function countdown(seconds: number): string {
  if (seconds <= 0) return "просрочено";
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60);
  if (minutes >= 60) return `${Math.floor(minutes / 60)} ч ${minutes % 60} мин`;
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

export const TEMPERATURE_STYLE: Record<Temperature, { label: string; className: string; dot: string }> = {
  COLD: {
    label: "COLD",
    className: "border-slate-600/60 bg-slate-700/25 text-slate-300",
    dot: "bg-slate-400",
  },
  WARM: {
    label: "WARM",
    className: "border-amber-500/40 bg-amber-500/10 text-amber-300",
    dot: "bg-amber-400",
  },
  HOT: {
    label: "HOT",
    className: "border-orange-500/50 bg-orange-500/15 text-orange-300",
    dot: "bg-orange-400",
  },
  CRITICAL: {
    label: "CRITICAL",
    className: "border-rose-500/50 bg-rose-500/15 text-rose-300",
    dot: "bg-rose-400",
  },
};

export const QUALITY_STYLE: Record<string, string> = {
  quality: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  qualified: "border-brand-500/40 bg-brand-500/10 text-brand-300",
  poor: "border-slate-600/60 bg-slate-700/25 text-slate-300",
  negative: "border-rose-500/40 bg-rose-500/10 text-rose-300",
  ignored: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  pending: "border-ink-600 bg-ink-800 text-slate-400",
};

export const scoreColor = (score: number) =>
  score >= 80 ? "text-emerald-400" : score >= 50 ? "text-amber-300" : "text-slate-400";

export const scoreBar = (score: number) =>
  score >= 80 ? "bg-emerald-500" : score >= 50 ? "bg-amber-400" : "bg-slate-500";

export const initials = (name: string) =>
  name
    .replace(/\(.*\)/, "")
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");

/**
 * Categorical series colours, assigned in fixed order and never cycled.
 *
 * Validated for the dark chart surface (#111527): lightness band, chroma floor,
 * CVD separation (worst adjacent ΔE 8.4), normal-vision floor (19.3) and 3:1
 * contrast all pass. The earlier indigo/sky pairing failed the normal-vision
 * floor — those two hues are hard to tell apart even with full colour vision.
 */
export const CHART_COLORS = [
  "#3987e5", // blue
  "#d95926", // orange
  "#199e70", // aqua
  "#c98500", // yellow
  "#d55181", // magenta
  "#9085e9", // violet
];

export const CHART_GRID = "rgba(148,163,184,.12)";
export const CHART_AXIS = "#94a3b8";
