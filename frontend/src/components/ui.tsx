import type { ReactNode } from "react";
import { AlertTriangle, Inbox } from "lucide-react";
import { TEMPERATURE_STYLE, initials, scoreBar, scoreColor } from "../lib/format";
import type { Temperature } from "../lib/api";

export function cx(...values: (string | false | null | undefined)[]) {
  return values.filter(Boolean).join(" ");
}

export function Card({
  children,
  className,
  ...rest
}: { children: ReactNode; className?: string } & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cx("card", className)} {...rest}>
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  subtitle,
  right,
  icon,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  right?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 px-5 py-4 border-b border-ink-700/70">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          {icon && <span className="text-brand-400">{icon}</span>}
          <h2 className="text-sm font-semibold text-slate-100 truncate">{title}</h2>
        </div>
        {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
      </div>
      {right && <div className="shrink-0">{right}</div>}
    </div>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone = "default",
  icon,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "default" | "good" | "warn" | "bad" | "brand";
  icon?: ReactNode;
}) {
  const toneClass = {
    default: "text-slate-100",
    good: "text-emerald-400",
    warn: "text-amber-300",
    bad: "text-rose-400",
    brand: "text-brand-300",
  }[tone];
  return (
    <Card className="p-4 card-hover">
      <div className="flex items-center justify-between">
        <p className="section-title">{label}</p>
        {icon && <span className="text-slate-600">{icon}</span>}
      </div>
      <p className={cx("mt-2 text-2xl font-semibold tabular-nums tracking-tight", toneClass)}>
        {value}
      </p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </Card>
  );
}

export function Badge({
  children,
  className,
  title,
}: {
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span title={title} className={cx("chip border-ink-600 bg-ink-800 text-slate-300", className)}>
      {children}
    </span>
  );
}

export function TemperatureBadge({ value, pulse }: { value: Temperature; pulse?: boolean }) {
  const style = TEMPERATURE_STYLE[value] ?? TEMPERATURE_STYLE.COLD;
  return (
    <span
      className={cx(
        "chip",
        style.className,
        pulse && value === "CRITICAL" && "animate-pulse-ring",
      )}
    >
      <span className={cx("h-1.5 w-1.5 rounded-full", style.dot)} />
      {style.label}
    </span>
  );
}

export function ScoreBar({ score, threshold }: { score: number; threshold?: number }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between">
        <span className="section-title">Qualification</span>
        <span className={cx("text-lg font-semibold tabular-nums", scoreColor(score))}>{score}%</span>
      </div>
      <div className="relative h-2 rounded-full bg-ink-800 overflow-hidden">
        <div
          className={cx("h-full rounded-full transition-all duration-500", scoreBar(score))}
          style={{ width: `${Math.min(100, Math.max(2, score))}%` }}
        />
        {threshold !== undefined && (
          <div
            className="absolute inset-y-0 w-px bg-slate-400/70"
            style={{ left: `${threshold}%` }}
            title={`Порог автопередачи: ${threshold}%`}
          />
        )}
      </div>
    </div>
  );
}

export function Avatar({
  name,
  color,
  size = "md",
}: {
  name: string;
  color?: string | null;
  size?: "sm" | "md" | "lg";
}) {
  const sizes = {
    sm: "h-7 w-7 text-[10px]",
    md: "h-9 w-9 text-xs",
    lg: "h-11 w-11 text-sm",
  }[size];
  return (
    <div
      className={cx(
        "shrink-0 rounded-full grid place-items-center font-semibold text-white/95 ring-1 ring-white/10",
        sizes,
      )}
      style={{ background: color ?? "#475569" }}
    >
      {initials(name)}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton", className)} />;
}

export function SkeletonList({ rows = 5, className }: { rows?: number; className?: string }) {
  return (
    <div className={cx("space-y-2 p-3", className)}>
      {Array.from({ length: rows }).map((_, index) => (
        <Skeleton key={index} className="h-14 w-full" />
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  hint,
  icon,
  action,
}: {
  title: string;
  hint?: string;
  icon?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
      <div className="grid h-12 w-12 place-items-center rounded-xl bg-ink-800 text-slate-500">
        {icon ?? <Inbox size={20} />}
      </div>
      <div>
        <p className="text-sm font-medium text-slate-300">{title}</p>
        {hint && <p className="mt-1 text-xs text-slate-500 max-w-sm">{hint}</p>}
      </div>
      {action}
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
      <AlertTriangle size={16} className="shrink-0" />
      <span>{message}</span>
    </div>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  hint,
  disabled,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: ReactNode;
  hint?: string;
  disabled?: boolean;
}) {
  return (
    <label
      className={cx(
        "flex items-center justify-between gap-4 py-2.5",
        disabled && "opacity-50 pointer-events-none",
      )}
    >
      <span className="min-w-0">
        <span className="block text-sm text-slate-200">{label}</span>
        {hint && <span className="block text-xs text-slate-500">{hint}</span>}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cx(
          "relative h-6 w-11 shrink-0 rounded-full transition",
          checked ? "bg-brand-600" : "bg-ink-600",
        )}
      >
        <span
          className={cx(
            "absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all",
            checked ? "left-[22px]" : "left-0.5",
          )}
        />
      </button>
    </label>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block space-y-1.5">
      <span className="block text-xs font-medium text-slate-400">{label}</span>
      {children}
      {hint && <span className="block text-[11px] text-slate-500">{hint}</span>}
    </label>
  );
}

export function Tooltip({ text, children }: { text: string; children: ReactNode }) {
  return (
    <span className="group relative inline-flex">
      {children}
      <span
        className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 hidden -translate-x-1/2
                   whitespace-nowrap rounded-md border border-ink-600 bg-ink-850 px-2 py-1 text-[11px]
                   text-slate-200 shadow-pop group-hover:block"
      >
        {text}
      </span>
    </span>
  );
}

export function Progress({ value, className }: { value: number; className?: string }) {
  return (
    <div className={cx("h-1.5 w-full rounded-full bg-ink-800 overflow-hidden", className)}>
      <div
        className="h-full rounded-full bg-brand-500 transition-all duration-500"
        style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
      />
    </div>
  );
}
