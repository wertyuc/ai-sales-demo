import { NavLink, useNavigate } from "react-router-dom";
import type { ReactNode } from "react";
import {
  Activity,
  BookOpen,
  BrainCircuit,
  Boxes,
  Clock,
  Gauge,
  KanbanSquare,
  LogOut,
  MessagesSquare,
  Sliders,
  Terminal,
  Zap,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api } from "../lib/api";
import type { ClockState, ProviderInfo } from "../lib/api";
import { usePoll } from "../hooks/usePoll";
import { cx } from "./ui";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** key in `operational` whose count is shown as a badge */
  badge?: string;
}

const NAV: NavItem[] = [
  { to: "/live", label: "Live Sales", icon: MessagesSquare, badge: "handoff_chats" },
  { to: "/crm", label: "CRM", icon: KanbanSquare, badge: "open_tasks" },
  { to: "/inventory", label: "Inventory", icon: Boxes },
  { to: "/followups", label: "Follow-ups", icon: Clock, badge: "scheduled_followups" },
  { to: "/analytics", label: "Analytics", icon: Gauge },
  { to: "/insights", label: "AI Insights", icon: BrainCircuit },
  { to: "/control", label: "Control Center", icon: Sliders },
  { to: "/kb", label: "Knowledge Base", icon: BookOpen },
  { to: "/logs", label: "Logs / Debug", icon: Terminal },
];

interface SystemInfo {
  app: string;
  environment: string;
  database: string;
  provider: ProviderInfo;
  clock: ClockState;
  operational: Record<string, number>;
}

export function Shell({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const { data } = usePoll<SystemInfo>(() => api.get<SystemInfo>("/api/system/info"), 5000);

  const logout = async () => {
    await api.post("/api/auth/logout");
    navigate("/login");
  };

  return (
    <div className="flex h-full min-h-screen">
      <aside className="hidden lg:flex w-[248px] shrink-0 flex-col border-r border-ink-800 bg-ink-900/70 backdrop-blur">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <div className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-sky-500 shadow-[0_6px_20px_-8px_rgba(99,102,241,.9)]">
            <Zap size={17} className="text-white" />
          </div>
          <div className="leading-tight">
            <p className="text-sm font-semibold text-slate-100">AI Sales Suite</p>
            <p className="text-[11px] text-slate-500">Avito · demo</p>
          </div>
        </div>

        <nav className="flex-1 space-y-0.5 px-3 py-2 scroll-y">
          {NAV.map(({ to, label, icon: Icon, badge }) => {
            const count = badge ? (data?.operational?.[badge] ?? 0) : 0;
            return (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  cx(
                    "group flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition",
                    isActive
                      ? "bg-brand-600/15 text-brand-200 ring-1 ring-brand-500/25"
                      : "text-slate-400 hover:bg-ink-800 hover:text-slate-200",
                  )
                }
              >
                <Icon size={16} className="shrink-0" />
                <span className="flex-1 truncate">{label}</span>
                {count > 0 && (
                  <span className="rounded-full bg-ink-700 px-1.5 py-0.5 text-[10px] font-semibold text-slate-300 tabular-nums">
                    {count}
                  </span>
                )}
              </NavLink>
            );
          })}
        </nav>

        <div className="space-y-3 border-t border-ink-800 px-4 py-4">
          <div className="rounded-lg bg-ink-850 px-3 py-2.5">
            <p className="section-title">LLM</p>
            <p className="mt-1 flex items-center gap-1.5 text-xs text-slate-300">
              <span
                className={cx(
                  "h-1.5 w-1.5 rounded-full",
                  data?.provider.configured ? "bg-emerald-400" : "bg-amber-400",
                )}
              />
              {data?.provider.provider ?? "—"}
            </p>
            <p className="mt-0.5 truncate text-[11px] text-slate-500" title={data?.provider.model}>
              {data?.provider.model ?? ""}
            </p>
          </div>
          <button onClick={logout} className="btn-ghost w-full">
            <LogOut size={15} /> Выйти
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar clock={data?.clock} operational={data?.operational} />
        <main className="min-h-0 flex-1 animate-fade-in">{children}</main>
      </div>
    </div>
  );
}

function TopBar({
  clock,
  operational,
}: {
  clock?: ClockState;
  operational?: Record<string, number>;
}) {
  const setSpeed = async (speed: number) => {
    await api.post("/api/live/clock/speed", { speed });
  };

  return (
    <header className="sticky top-0 z-30 flex items-center gap-4 border-b border-ink-800 bg-ink-950/85 px-5 py-3 backdrop-blur">
      <div className="flex items-center gap-2 lg:hidden">
        <Zap size={16} className="text-brand-400" />
        <span className="text-sm font-semibold">AI Sales Suite</span>
      </div>

      <div className="hidden items-center gap-2 sm:flex">
        <Activity size={15} className="text-slate-500" />
        <span className="text-xs text-slate-500">Демо-время</span>
        <span className="rounded-md bg-ink-850 px-2 py-1 font-mono text-xs text-slate-200 tabular-nums">
          {clock ? new Date(clock.now).toLocaleString("ru-RU", {
            day: "2-digit",
            month: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          }) : "—"}
        </span>
      </div>

      <div className="ml-auto flex items-center gap-3">
        {operational && operational.overdue_tasks > 0 && (
          <span className="chip border-rose-500/40 bg-rose-500/10 text-rose-300">
            SLA просрочено: {operational.overdue_tasks}
          </span>
        )}
        <div className="flex items-center gap-1 rounded-lg border border-ink-700 bg-ink-850 p-1">
          <span className="px-1.5 text-[11px] text-slate-500">Скорость</span>
          {(clock?.allowed_speeds ?? [1, 10, 60, 100, 600]).map((speed) => (
            <button
              key={speed}
              onClick={() => void setSpeed(speed)}
              className={cx(
                "rounded px-2 py-1 text-[11px] font-medium tabular-nums transition",
                clock?.speed === speed
                  ? "bg-brand-600 text-white"
                  : "text-slate-400 hover:bg-ink-700 hover:text-slate-200",
              )}
              title={
                speed === 1
                  ? "Реальное время"
                  : `1 секунда = ${speed} демо-секунд (${Math.round(speed / 60) || "<1"} мин)`
              }
            >
              ×{speed}
            </button>
          ))}
        </div>
      </div>
    </header>
  );
}
