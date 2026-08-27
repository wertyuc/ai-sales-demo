import { useCallback, useState } from "react";
import {
  Briefcase,
  CalendarClock,
  CheckCircle2,
  CircleDollarSign,
  Phone,
  Timer,
  UserCheck,
  Users,
  X,
} from "lucide-react";
import { api } from "../lib/api";
import type { LeadCard, ManagerRow } from "../lib/api";
import { usePoll } from "../hooks/usePoll";
import { QUALITY_STYLE, countdown, dateTimeOf, money, scoreColor } from "../lib/format";
import {
  Avatar,
  Badge,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  Skeleton,
  TemperatureBadge,
  Toggle,
  cx,
} from "../components/ui";

interface BoardResponse {
  columns: { key: string; label: string; cards: LeadCard[] }[];
  directions: { key: string; label: string }[];
  quality_labels: Record<string, string>;
  total: number;
}

interface TaskRow {
  id: number;
  lead_id: number;
  customer: string;
  title: string;
  reason: string;
  status: string;
  manager: string | null;
  manager_color: string | null;
  deadline: string;
  seconds_left: number;
}

export default function CRM() {
  const [tab, setTab] = useState<"board" | "tasks" | "managers">("board");
  const [openLead, setOpenLead] = useState<number | null>(null);

  const board = usePoll<BoardResponse>(() => api.get<BoardResponse>("/api/crm/board"), 5000);

  return (
    <div className="flex h-[calc(100vh-57px)] min-h-0 flex-col">
      <div className="flex items-center gap-3 border-b border-ink-800 px-6 py-3">
        <h1 className="text-sm font-semibold text-slate-100">CRM</h1>
        <span className="text-[11px] text-slate-500">
          Demo-воронка · имитирует Bitrix24 ({board.data?.total ?? 0} лидов)
        </span>
        <div className="ml-auto flex gap-1 rounded-lg border border-ink-700 bg-ink-850 p-1">
          {([
            ["board", "Воронка"],
            ["tasks", "Задачи"],
            ["managers", "Менеджеры"],
          ] as const).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={cx(
                "rounded px-3 py-1 text-xs font-medium transition",
                tab === key ? "bg-brand-600 text-white" : "text-slate-400 hover:text-slate-200",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1">
        {tab === "board" && (
          <Board
            data={board.data}
            loading={board.loading}
            error={board.error}
            onOpen={setOpenLead}
            onChanged={() => void board.refresh()}
          />
        )}
        {tab === "tasks" && <Tasks />}
        {tab === "managers" && <Managers />}
      </div>

      {openLead !== null && (
        <LeadDrawer
          leadId={openLead}
          onClose={() => setOpenLead(null)}
          onChanged={() => void board.refresh()}
        />
      )}
    </div>
  );
}

function Board({
  data,
  loading,
  error,
  onOpen,
  onChanged,
}: {
  data: BoardResponse | null;
  loading: boolean;
  error: string | null;
  onOpen: (id: number) => void;
  onChanged: () => void;
}) {
  const [dragging, setDragging] = useState<number | null>(null);

  const drop = async (stage: string) => {
    if (dragging === null) return;
    await api.post(`/api/crm/leads/${dragging}/stage`, { stage });
    setDragging(null);
    onChanged();
  };

  if (error) return <div className="p-6"><ErrorState message={error} /></div>;

  return (
    <div className="h-full scroll-y overflow-x-auto p-5">
      <div className="flex h-full min-w-max gap-4">
        {(data?.columns ?? []).map((column) => (
          <div
            key={column.key}
            onDragOver={(event) => event.preventDefault()}
            onDrop={() => void drop(column.key)}
            className="flex w-[290px] shrink-0 flex-col rounded-xl border border-ink-800 bg-ink-900/40"
          >
            <div className="flex items-center justify-between border-b border-ink-800 px-3.5 py-2.5">
              <p className="text-xs font-semibold text-slate-200">{column.label}</p>
              <span className="rounded-full bg-ink-800 px-1.5 py-0.5 text-[10px] text-slate-400 tabular-nums">
                {column.cards.length}
              </span>
            </div>
            <div className="min-h-0 flex-1 space-y-2 scroll-y p-2.5">
              {loading && !data ? (
                <>
                  <Skeleton className="h-28 w-full" />
                  <Skeleton className="h-28 w-full" />
                </>
              ) : column.cards.length === 0 ? (
                <p className="px-2 py-6 text-center text-[11px] text-slate-600">Пусто</p>
              ) : (
                column.cards.map((card) => (
                  <article
                    key={card.id}
                    draggable
                    onDragStart={() => setDragging(card.id)}
                    onDragEnd={() => setDragging(null)}
                    onClick={() => onOpen(card.id)}
                    className={cx(
                      "cursor-pointer rounded-lg border border-ink-700 bg-ink-850 p-3 transition",
                      "hover:border-brand-500/50 hover:shadow-pop",
                      dragging === card.id && "opacity-40",
                    )}
                  >
                    <div className="flex items-start gap-2.5">
                      <Avatar name={card.customer.name} color={card.customer.color} size="sm" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-xs font-medium text-slate-100">
                          {card.customer.name}
                        </p>
                        <p className="truncate text-[10px] text-slate-500">
                          {card.customer.source} · {card.direction_label}
                        </p>
                      </div>
                      <span className={cx("text-[11px] font-semibold tabular-nums", scoreColor(card.score))}>
                        {card.score}%
                      </span>
                    </div>

                    <div className="mt-2 space-y-0.5 text-[11px] text-slate-400">
                      {card.budget && <p className="truncate">💰 {card.budget}</p>}
                      {card.location && <p className="truncate">📍 {card.location}</p>}
                      {card.needs && <p className="truncate">🎯 {card.needs}</p>}
                    </div>

                    <div className="mt-2 flex flex-wrap items-center gap-1">
                      <TemperatureBadge value={card.temperature} />
                      <Badge className={QUALITY_STYLE[card.quality] ?? ""}>{card.quality_label}</Badge>
                      {card.contact_acquired && (
                        <Badge className="border-emerald-500/40 bg-emerald-500/10 text-emerald-300">
                          <Phone size={10} /> контакт
                        </Badge>
                      )}
                    </div>

                    {card.manager && (
                      <p className="mt-2 flex items-center gap-1.5 text-[10px] text-slate-500">
                        <span
                          className="h-1.5 w-1.5 rounded-full"
                          style={{ background: card.manager_color ?? "#64748b" }}
                        />
                        {card.manager}
                      </p>
                    )}
                  </article>
                ))
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function LeadDrawer({
  leadId,
  onClose,
  onChanged,
}: {
  leadId: number;
  onClose: () => void;
  onChanged: () => void;
}) {
  const loader = useCallback(() => api.get<LeadCard>(`/api/crm/leads/${leadId}`), [leadId]);
  const { data, loading, refresh } = usePoll<LeadCard>(loader, 6000, [leadId]);
  const [notes, setNotes] = useState<string | null>(null);

  const mark = async (payload: Record<string, unknown>) => {
    await api.post(`/api/crm/leads/${leadId}/outcome`, payload);
    await refresh();
    onChanged();
  };

  const saveNotes = async () => {
    if (notes === null) return;
    await api.post(`/api/crm/leads/${leadId}/notes`, { notes });
    setNotes(null);
    await refresh();
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50 backdrop-blur-sm" onClick={onClose}>
      <div
        className="h-full w-full max-w-[520px] overflow-y-auto border-l border-ink-700 bg-ink-900 animate-fade-in"
        onClick={(event) => event.stopPropagation()}
      >
        {loading && !data ? (
          <div className="space-y-3 p-6">
            <Skeleton className="h-8 w-1/2" />
            <Skeleton className="h-40 w-full" />
          </div>
        ) : !data ? null : (
          <>
            <div className="sticky top-0 z-10 flex items-start gap-3 border-b border-ink-700 bg-ink-900 px-5 py-4">
              <Avatar name={data.customer.name} color={data.customer.color} size="lg" />
              <div className="min-w-0 flex-1">
                <h2 className="text-sm font-semibold text-slate-100">{data.customer.name}</h2>
                <p className="text-[11px] text-slate-500">
                  {data.customer.avito_id} · {data.customer.source}
                </p>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  <TemperatureBadge value={data.temperature} />
                  <Badge>{data.stage_label}</Badge>
                  <Badge>{data.direction_label}</Badge>
                  <Badge className={QUALITY_STYLE[data.quality] ?? ""}>{data.quality_label}</Badge>
                </div>
              </div>
              <button className="btn-ghost px-2" onClick={onClose}>
                <X size={15} />
              </button>
            </div>

            <div className="space-y-5 p-5">
              <div className="grid grid-cols-2 gap-2">
                <Detail label="Qualification" value={`${data.score}% · ${data.closed_count}/6`} />
                <Detail label="Телефон" value={data.customer.phone || "не получен"} />
                <Detail label="Бюджет" value={data.budget || "—"} />
                <Detail label="География" value={data.location || "—"} />
                <Detail label="Задачи" value={data.needs || "—"} />
                <Detail label="Срок" value={data.timeframe || "—"} />
                <Detail label="Получатель" value={data.recipient || "—"} />
                <Detail label="Менеджер" value={data.manager || "не назначен"} />
              </div>

              {data.handoff_required && (
                <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-3 py-2.5">
                  <p className="text-xs font-semibold text-amber-200">Передан менеджеру</p>
                  <p className="mt-0.5 text-[11px] text-slate-300">{data.handoff_reason}</p>
                </div>
              )}

              {data.products.length > 0 && (
                <section>
                  <p className="section-title mb-2">Выбранные модели</p>
                  <ul className="space-y-1.5">
                    {data.products.map((product) => (
                      <li key={product.id} className="flex items-center justify-between rounded-lg bg-ink-850 px-3 py-2">
                        <span className="truncate text-xs text-slate-200">{product.title}</span>
                        <span className="shrink-0 text-[11px] text-slate-400">от {money(product.price)}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {data.meeting && (
                <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-2.5">
                  <p className="flex items-center gap-1.5 text-xs font-semibold text-emerald-200">
                    <CalendarClock size={13} /> Встреча {dateTimeOf(data.meeting.at)}
                  </p>
                  <p className="mt-0.5 text-[11px] text-slate-400">Статус: {data.meeting.status}</p>
                </div>
              )}

              {data.task && (
                <div className="rounded-xl border border-ink-600 bg-ink-850 px-3 py-2.5">
                  <p className="flex items-center gap-1.5 text-xs font-semibold text-slate-200">
                    <Timer size={13} /> {data.task.title}
                  </p>
                  <p className="mt-0.5 text-[11px] text-slate-400">
                    Дедлайн {dateTimeOf(data.task.deadline)} · {data.task.status}
                  </p>
                </div>
              )}

              <section>
                <p className="section-title mb-1.5">Next action</p>
                <p className="rounded-lg bg-brand-600/10 px-3 py-2 text-xs text-slate-200 ring-1 ring-brand-500/25">
                  {data.next_action || "—"}
                </p>
              </section>

              <section>
                <p className="section-title mb-1.5">Заметки</p>
                <textarea
                  value={notes ?? data.notes}
                  onChange={(event) => setNotes(event.target.value)}
                  rows={3}
                  className="w-full resize-none"
                  placeholder="Комментарий менеджера…"
                />
                {notes !== null && (
                  <button className="btn-primary mt-2" onClick={() => void saveNotes()}>
                    Сохранить
                  </button>
                )}
              </section>

              <section className="space-y-2">
                <p className="section-title">Результат сделки</p>
                <div className="flex flex-wrap gap-2">
                  <button
                    className={cx("btn-ghost", data.arrived && "border-emerald-500/40 text-emerald-300")}
                    onClick={() => void mark({ arrived: !data.arrived })}
                  >
                    <UserCheck size={14} /> {data.arrived ? "Приехал" : "Отметить приход"}
                  </button>
                  <button
                    className={cx("btn-ghost", data.sold && "border-emerald-500/40 text-emerald-300")}
                    onClick={() => void mark({ sold: !data.sold, sale_amount: data.products[0]?.price ?? 0 })}
                  >
                    <CircleDollarSign size={14} /> {data.sold ? "Продано" : "Отметить продажу"}
                  </button>
                </div>
              </section>

              {data.history && data.history.length > 0 && (
                <section>
                  <p className="section-title mb-2">История изменений</p>
                  <ul className="space-y-1.5">
                    {data.history.map((row, index) => (
                      <li key={index} className="rounded-lg bg-ink-850 px-3 py-2 text-[11px]">
                        <p className="text-slate-300">
                          {row.field}: <span className="text-slate-500">{row.old || "—"}</span> →{" "}
                          <span className="text-slate-100">{row.new}</span>
                        </p>
                        <p className="mt-0.5 text-slate-600">
                          {dateTimeOf(row.at)} · {row.actor}
                        </p>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-ink-850 px-3 py-2">
      <p className="text-[10px] text-slate-500">{label}</p>
      <p className="mt-0.5 truncate text-xs text-slate-100">{value}</p>
    </div>
  );
}

function Tasks() {
  const { data, loading, refresh } = usePoll<{ items: TaskRow[] }>(
    () => api.get("/api/crm/tasks"),
    3000,
  );

  const complete = async (id: number) => {
    await api.post(`/api/crm/tasks/${id}/done`);
    await refresh();
  };

  return (
    <div className="h-full scroll-y p-6">
      <Card>
        <CardHeader
          title="Задачи менеджерам"
          subtitle="Создаются автоматически при передаче. Дедлайн — 5 минут (§28.6)."
          icon={<Briefcase size={15} />}
        />
        {loading && !data ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}
          </div>
        ) : !data?.items.length ? (
          <EmptyState title="Задач нет" hint="Передайте диалог менеджеру — задача появится здесь." />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-ink-800 text-left text-[11px] uppercase tracking-wide text-slate-500">
                <th className="px-5 py-2.5 font-medium">Клиент</th>
                <th className="px-3 py-2.5 font-medium">Задача</th>
                <th className="px-3 py-2.5 font-medium">Менеджер</th>
                <th className="px-3 py-2.5 font-medium">Дедлайн</th>
                <th className="px-3 py-2.5 font-medium">SLA</th>
                <th className="px-5 py-2.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-800/70">
              {data.items.map((task) => (
                <tr key={task.id} className="hover:bg-ink-850/40">
                  <td className="px-5 py-2.5 text-slate-200">{task.customer}</td>
                  <td className="px-3 py-2.5">
                    <p className="text-slate-200">{task.title}</p>
                    <p className="text-[11px] text-slate-500">{task.reason}</p>
                  </td>
                  <td className="px-3 py-2.5">
                    {task.manager ? (
                      <span className="flex items-center gap-1.5 text-slate-300">
                        <span className="h-1.5 w-1.5 rounded-full" style={{ background: task.manager_color ?? "#64748b" }} />
                        {task.manager}
                      </span>
                    ) : (
                      <span className="text-slate-600">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-[11px] text-slate-400">{dateTimeOf(task.deadline)}</td>
                  <td className="px-3 py-2.5">
                    {task.status === "done" ? (
                      <Badge className="border-emerald-500/40 bg-emerald-500/10 text-emerald-300">
                        <CheckCircle2 size={11} /> выполнена
                      </Badge>
                    ) : task.seconds_left <= 0 ? (
                      <Badge className="border-rose-500/40 bg-rose-500/10 text-rose-300">просрочена</Badge>
                    ) : (
                      <Badge className="border-amber-500/40 bg-amber-500/10 text-amber-300">
                        <Timer size={11} /> {countdown(task.seconds_left)}
                      </Badge>
                    )}
                  </td>
                  <td className="px-5 py-2.5 text-right">
                    {task.status !== "done" && (
                      <button className="btn-ghost px-2 py-1 text-xs" onClick={() => void complete(task.id)}>
                        Закрыть
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

function Managers() {
  const { data, loading, refresh } = usePoll<{
    items: ManagerRow[];
    history: { at: string; manager: string; reason: string; rule: string; on_shift: string[] }[];
    on_shift: string[];
  }>(() => api.get("/api/crm/managers"), 5000);

  const toggleShift = async (id: number, value: boolean) => {
    await api.post(`/api/crm/managers/${id}/shift`, { on_shift: value });
    await refresh();
  };

  return (
    <div className="h-full scroll-y p-6">
      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Менеджеры на смене"
            subtitle="Один на смене — получает всё. Двое — квалифицированные лиды распределяются по очереди."
            icon={<Users size={15} />}
          />
          <div className="divide-y divide-ink-800/70 px-5">
            {loading && !data ? (
              <div className="space-y-2 py-4">
                <Skeleton className="h-12 w-full" />
                <Skeleton className="h-12 w-full" />
              </div>
            ) : (
              data?.items.map((manager) => (
                <div key={manager.id} className="py-1">
                  <Toggle
                    checked={manager.on_shift}
                    onChange={(value) => void toggleShift(manager.id, value)}
                    label={
                      <span className="flex items-center gap-2">
                        <span className="h-2 w-2 rounded-full" style={{ background: manager.color }} />
                        {manager.name}
                        <span className="text-[11px] text-slate-500">
                          {manager.role === "service" ? "сервис" : "продажи"}
                        </span>
                      </span>
                    }
                    hint={`Назначено ${manager.assigned_total} · лидов ${manager.leads} · открытых задач ${manager.open_tasks}`}
                  />
                </div>
              ))
            )}
          </div>
        </Card>

        <Card>
          <CardHeader title="История назначений" subtitle="Round-robin между менеджерами на смене" />
          <div className="max-h-[420px] scroll-y p-4">
            {!data?.history.length ? (
              <EmptyState title="Назначений пока нет" />
            ) : (
              <ul className="space-y-2">
                {data.history.map((row, index) => (
                  <li key={index} className="rounded-lg bg-ink-850 px-3 py-2">
                    <p className="text-xs text-slate-200">
                      {row.manager} <span className="text-slate-500">· {row.rule}</span>
                    </p>
                    <p className="mt-0.5 text-[11px] text-slate-500">{row.reason}</p>
                    <p className="mt-0.5 text-[10px] text-slate-600">
                      {dateTimeOf(row.at)} · на смене: {(row.on_shift ?? []).join(", ") || "—"}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
