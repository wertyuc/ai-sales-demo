import { BellRing, CalendarClock, Clock, Play, Send, XCircle } from "lucide-react";
import { api } from "../lib/api";
import type { ClockState, FollowUpRow } from "../lib/api";
import { usePoll } from "../hooks/usePoll";
import { countdown, dateTimeOf, relativeTo } from "../lib/format";
import { Avatar, Badge, Card, CardHeader, EmptyState, Skeleton, Stat, cx } from "../components/ui";

interface FollowUpsResponse {
  items: FollowUpRow[];
  scheduled: FollowUpRow[];
  sent: FollowUpRow[];
  blocked: FollowUpRow[];
  rules: Record<string, unknown>;
  clock: ClockState;
  scheduler: { ticks: number; sent: number; postponed: number; last_run: string | null };
}

const RULE_LABELS: Record<string, string> = {
  first_delay: "через 15 минут (прочитано)",
  second_delay: "через 1 час",
  evening: "вечером",
  daily: "1 раз в сутки",
  day_before: "за день до встречи",
  morning: "утром в день встречи",
  hour_before: "за час до встречи",
};

export default function FollowUps() {
  const { data, loading, refresh } = usePoll<FollowUpsResponse>(
    () => api.get<FollowUpsResponse>("/api/followups"),
    2500,
  );

  const runNow = async (id: number) => {
    await api.post(`/api/followups/${id}/run-now`);
    await refresh();
  };
  const cancel = async (id: number) => {
    await api.post(`/api/followups/${id}/cancel`);
    await refresh();
  };

  const rules = data?.rules ?? {};

  return (
    <div className="h-full scroll-y p-6 space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-slate-100">Follow-ups</h1>
        <p className="mt-0.5 text-xs text-slate-500">
          Планировщик работает по демо-часам. Ускорьте время в шапке — правила §12 отработают
          за секунды.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Запланировано" value={data?.scheduled.length ?? "—"} icon={<Clock size={15} />} />
        <Stat label="Отправлено" value={data?.sent.length ?? "—"} tone="good" icon={<Send size={15} />} />
        <Stat label="Остановлено" value={data?.blocked.length ?? "—"} tone="warn" />
        <Stat
          label="Тиков планировщика"
          value={data?.scheduler.ticks ?? "—"}
          hint={data?.scheduler.last_run ? `последний: ${dateTimeOf(data.scheduler.last_run)}` : undefined}
        />
      </div>

      <Card className="p-4">
        <p className="section-title mb-2">Действующие правила</p>
        <div className="flex flex-wrap gap-2 text-[11px]">
          <Badge>1-е касание: {String(rules.first_delay_minutes ?? 15)} мин</Badge>
          <Badge>2-е касание: {String(rules.second_delay_minutes ?? 60)} мин</Badge>
          <Badge>вечером: {String(rules.evening_hour ?? 19)}:00</Badge>
          <Badge>не читает → максимум {String(rules.max_unread_touches ?? 2)} касания</Badge>
          <Badge>читает и молчит → {String(rules.max_touches_per_day ?? 1)} раз в сутки</Badge>
          <Badge className="border-brand-500/40 bg-brand-500/10 text-brand-200">
            окна: {(rules.windows as string[] | undefined)?.join(", ") ?? "—"}
          </Badge>
        </div>
        <p className="mt-2 text-[11px] text-slate-600">
          Правила меняются в Control Center → Follow-up и применяются к следующему касанию.
        </p>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Запланированные касания"
            subtitle="Отсчёт идёт по демо-времени"
            icon={<CalendarClock size={15} />}
          />
          {loading && !data ? (
            <div className="space-y-2 p-4">
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-16 w-full" />
            </div>
          ) : !data?.scheduled.length ? (
            <EmptyState
              title="Нет запланированных касаний"
              hint="Напишите в Live Sales от имени клиента и не отвечайте — планировщик поставит касание через 15 минут."
            />
          ) : (
            <ul className="divide-y divide-ink-800/70">
              {data.scheduled.map((row) => (
                <li key={row.id} className="flex items-start gap-3 px-5 py-3">
                  <Avatar name={row.customer} color={row.customer_color} size="sm" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="truncate text-sm text-slate-100">{row.customer}</p>
                      {row.kind === "meeting_reminder" && (
                        <Badge className="border-emerald-500/40 bg-emerald-500/10 text-emerald-300">
                          <BellRing size={10} /> встреча
                        </Badge>
                      )}
                    </div>
                    <p className="mt-0.5 text-[11px] text-slate-500">
                      Попытка {row.attempt} · {RULE_LABELS[row.rule] ?? row.rule}
                    </p>
                    {row.note && <p className="mt-0.5 text-[11px] text-amber-300/80">{row.note}</p>}
                    <p className="mt-1 text-[11px] text-slate-400">
                      {dateTimeOf(row.due_at)} ·{" "}
                      <span className={row.seconds_left <= 0 ? "text-amber-300" : "text-slate-500"}>
                        {countdown(row.seconds_left)}
                      </span>
                    </p>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    <button
                      className="btn-ghost px-2 py-1 text-[11px]"
                      onClick={() => void runNow(row.id)}
                      title="Отправить на следующем тике"
                    >
                      <Play size={12} />
                    </button>
                    <button
                      className="btn-ghost px-2 py-1 text-[11px]"
                      onClick={() => void cancel(row.id)}
                      title="Отменить"
                    >
                      <XCircle size={12} />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <CardHeader title="История касаний" subtitle="Что уже ушло клиенту" icon={<Send size={15} />} />
          {!data?.sent.length && !data?.blocked.length ? (
            <EmptyState title="История пуста" />
          ) : (
            <ul className="max-h-[460px] divide-y divide-ink-800/70 scroll-y">
              {[...(data?.sent ?? []), ...(data?.blocked ?? [])]
                .sort((a, b) => (b.sent_at ?? b.due_at).localeCompare(a.sent_at ?? a.due_at))
                .slice(0, 40)
                .map((row) => (
                  <li key={`${row.status}-${row.id}`} className="flex items-start gap-3 px-5 py-3">
                    <Avatar name={row.customer} color={row.customer_color} size="sm" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm text-slate-200">{row.customer}</p>
                      <p className="mt-0.5 text-[11px] text-slate-500">
                        {RULE_LABELS[row.rule] ?? row.rule} · попытка {row.attempt}
                      </p>
                      {row.note && <p className="text-[11px] text-slate-600">{row.note}</p>}
                    </div>
                    <div className="shrink-0 text-right">
                      <Badge
                        className={cx(
                          row.status === "sent"
                            ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                            : row.status === "blocked"
                              ? "border-rose-500/40 bg-rose-500/10 text-rose-300"
                              : "",
                        )}
                      >
                        {row.status === "sent" ? "отправлено" : row.status === "blocked" ? "остановлено" : "отменено"}
                      </Badge>
                      <p className="mt-1 text-[10px] text-slate-600">
                        {row.sent_at ? relativeTo(row.sent_at, data?.clock.now) : ""}
                      </p>
                      {row.unread && <p className="text-[10px] text-amber-400">не прочитано</p>}
                    </div>
                  </li>
                ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
