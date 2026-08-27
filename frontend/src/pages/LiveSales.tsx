import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertOctagon,
  Bot,
  CheckCircle2,
  ChevronRight,
  Eye,
  EyeOff,
  MapPin,
  Phone,
  Play,
  Plus,
  Send,
  Sparkles,
  Timer,
  User,
  UserCog,
  X,
} from "lucide-react";
import { api } from "../lib/api";
import type {
  ChatMessage,
  ClockState,
  ConversationSummary,
  Intelligence,
  ProviderInfo,
  ScenarioInfo,
} from "../lib/api";
import { usePoll } from "../hooks/usePoll";
import {
  countdown,
  dateTimeOf,
  money,
  relativeTo,
  scoreColor,
  timeOf,
} from "../lib/format";
import {
  Avatar,
  Badge,
  Card,
  EmptyState,
  ErrorState,
  ScoreBar,
  SkeletonList,
  TemperatureBadge,
  Tooltip,
  cx,
} from "../components/ui";

interface ListResponse {
  items: ConversationSummary[];
  clock: ClockState;
  provider: ProviderInfo;
}

interface DetailResponse {
  conversation: ConversationSummary;
  messages: ChatMessage[];
  intelligence: Intelligence;
  clock: ClockState;
}

export default function LiveSales() {
  const [selected, setSelected] = useState<number | null>(null);
  const [showScenarios, setShowScenarios] = useState(false);
  const [showNew, setShowNew] = useState(false);

  const list = usePoll<ListResponse>(
    () => api.get<ListResponse>("/api/live/conversations"),
    4000,
  );

  useEffect(() => {
    if (selected === null && list.data?.items.length) {
      setSelected(list.data.items[0].id);
    }
  }, [list.data, selected]);

  return (
    <div className="flex h-[calc(100vh-57px)] min-h-0">
      <ConversationList
        items={list.data?.items ?? []}
        loading={list.loading}
        selected={selected}
        onSelect={setSelected}
        clockNow={list.data?.clock.now}
        onNew={() => setShowNew(true)}
        onScenarios={() => setShowScenarios(true)}
      />
      {selected === null ? (
        <div className="flex-1 grid place-items-center">
          <EmptyState
            title="Выберите диалог"
            hint="Слева — входящие обращения из Avito. Или запустите готовый демо-сценарий."
            icon={<Bot size={20} />}
            action={
              <button className="btn-primary" onClick={() => setShowScenarios(true)}>
                <Play size={15} /> Run Demo Scenario
              </button>
            }
          />
        </div>
      ) : (
        <ChatPane
          conversationId={selected}
          onChanged={() => void list.refresh()}
          onClosed={() => setSelected(null)}
        />
      )}

      {showScenarios && (
        <ScenarioDialog
          onClose={() => setShowScenarios(false)}
          onDone={(conversationId) => {
            setShowScenarios(false);
            setSelected(conversationId);
            void list.refresh();
          }}
        />
      )}
      {showNew && (
        <NewConversationDialog
          onClose={() => setShowNew(false)}
          onDone={(conversationId) => {
            setShowNew(false);
            setSelected(conversationId);
            void list.refresh();
          }}
        />
      )}
    </div>
  );
}

// --- left column -------------------------------------------------------------

function ConversationList({
  items,
  loading,
  selected,
  onSelect,
  clockNow,
  onNew,
  onScenarios,
}: {
  items: ConversationSummary[];
  loading: boolean;
  selected: number | null;
  onSelect: (id: number) => void;
  clockNow?: string;
  onNew: () => void;
  onScenarios: () => void;
}) {
  const [filter, setFilter] = useState("");
  const visible = useMemo(() => {
    const query = filter.trim().toLowerCase();
    if (!query) return items;
    return items.filter(
      (item) =>
        item.customer.name.toLowerCase().includes(query) ||
        item.last_message.toLowerCase().includes(query),
    );
  }, [items, filter]);

  return (
    <div className="flex w-[320px] shrink-0 flex-col border-r border-ink-800 bg-ink-900/40">
      <div className="space-y-3 border-b border-ink-800 px-4 py-3.5">
        <div className="flex items-center justify-between">
          <h1 className="text-sm font-semibold text-slate-100">Диалоги</h1>
          <span className="text-[11px] text-slate-500">{items.length}</span>
        </div>
        <input
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="Поиск по имени или тексту…"
          className="w-full"
        />
        <div className="grid grid-cols-2 gap-2">
          <button className="btn-primary" onClick={onScenarios}>
            <Play size={14} /> Сценарий
          </button>
          <button className="btn-ghost" onClick={onNew}>
            <Plus size={14} /> Диалог
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 scroll-y">
        {loading && items.length === 0 ? (
          <SkeletonList rows={7} />
        ) : visible.length === 0 ? (
          <EmptyState title="Ничего не найдено" hint="Измените запрос или создайте диалог." />
        ) : (
          <ul className="divide-y divide-ink-800/70">
            {visible.map((item) => (
              <li key={item.id}>
                <button
                  onClick={() => onSelect(item.id)}
                  className={cx(
                    "w-full px-4 py-3 text-left transition",
                    selected === item.id ? "bg-brand-600/10" : "hover:bg-ink-850/60",
                  )}
                >
                  <div className="flex items-start gap-3">
                    <Avatar name={item.customer.name} color={item.customer.color} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <p className="truncate text-sm font-medium text-slate-100">
                          {item.customer.name}
                        </p>
                        <span className="ml-auto shrink-0 text-[10px] text-slate-500">
                          {timeOf(item.last_message_at)}
                        </span>
                      </div>
                      <p className="mt-0.5 truncate text-xs text-slate-400">
                        {item.last_message_role === "customer" ? "" : "AI: "}
                        {item.last_message || "—"}
                      </p>
                      <div className="mt-2 flex flex-wrap items-center gap-1.5">
                        <TemperatureBadge value={item.temperature} pulse />
                        <span className={cx("text-[11px] font-semibold tabular-nums", scoreColor(item.score))}>
                          {item.score}%
                        </span>
                        {item.mode === "human" && (
                          <Badge className="border-sky-500/40 bg-sky-500/10 text-sky-300">
                            <UserCog size={11} /> Human
                          </Badge>
                        )}
                        {item.handoff_required && item.mode !== "human" && (
                          <Badge className="border-amber-500/40 bg-amber-500/10 text-amber-300">
                            handoff
                          </Badge>
                        )}
                      </div>
                    </div>
                  </div>
                  {clockNow && item.last_message_at && (
                    <p className="mt-1.5 pl-12 text-[10px] text-slate-600">
                      {relativeTo(item.last_message_at, clockNow)}
                    </p>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

// --- centre column -----------------------------------------------------------

function ChatPane({
  conversationId,
  onChanged,
  onClosed,
}: {
  conversationId: number;
  onChanged: () => void;
  onClosed: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [asManager, setAsManager] = useState(false);
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const loader = useCallback(
    () => api.get<DetailResponse>(`/api/live/conversations/${conversationId}`),
    [conversationId],
  );
  const detail = usePoll<DetailResponse>(loader, 2500, [conversationId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [detail.data?.messages.length]);

  const send = async () => {
    const text = draft.trim();
    if (!text || sending) return;
    setSending(true);
    setDraft("");
    try {
      const endpoint = asManager ? "manager-message" : "messages";
      await api.post(`/api/live/conversations/${conversationId}/${endpoint}`, { text });
      await detail.refresh();
      onChanged();
    } catch (error) {
      setDraft(text);
      // eslint-disable-next-line no-console
      console.error(error);
    } finally {
      setSending(false);
    }
  };

  const setMode = async (mode: "ai" | "human") => {
    await api.post(`/api/live/conversations/${conversationId}/mode`, { mode });
    await detail.refresh();
    onChanged();
  };

  const toggleRead = async () => {
    await api.post(`/api/live/conversations/${conversationId}/read`);
    await detail.refresh();
  };

  const remove = async () => {
    await api.del(`/api/live/conversations/${conversationId}`);
    onClosed();
    onChanged();
  };

  if (detail.error) {
    return (
      <div className="flex-1 p-6">
        <ErrorState message={detail.error} />
      </div>
    );
  }

  const conversation = detail.data?.conversation;
  const messages = detail.data?.messages ?? [];
  const isHuman = conversation?.mode === "human";

  return (
    <>
      <section className="flex min-w-0 flex-1 flex-col bg-ink-950/40">
        <header className="flex items-center gap-3 border-b border-ink-800 px-5 py-3">
          {conversation && (
            <>
              <Avatar name={conversation.customer.name} color={conversation.customer.color} size="lg" />
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <h2 className="truncate text-sm font-semibold text-slate-100">
                    {conversation.customer.name}
                  </h2>
                  <Badge>{conversation.customer.source}</Badge>
                </div>
                <p className="text-[11px] text-slate-500">
                  Avito ID {conversation.customer.avito_id} ·{" "}
                  {conversation.customer.phone || "телефон не получен"}
                </p>
              </div>
            </>
          )}

          <div className="ml-auto flex items-center gap-2">
            <Tooltip text="Читает ли клиент сообщения — управляет правилами follow-up (§12)">
              <button className="btn-ghost" onClick={() => void toggleRead()}>
                {messages.some((m) => m.role === "ai" && !m.read_at) ? (
                  <EyeOff size={14} />
                ) : (
                  <Eye size={14} />
                )}
                Прочтение
              </button>
            </Tooltip>
            {isHuman ? (
              <button className="btn-primary" onClick={() => void setMode("ai")}>
                <Bot size={14} /> Return to AI
              </button>
            ) : (
              <button className="btn-ghost" onClick={() => void setMode("human")}>
                <UserCog size={14} /> Take over chat
              </button>
            )}
            <Tooltip text="Удалить демо-диалог">
              <button className="btn-ghost px-2" onClick={() => void remove()}>
                <X size={14} />
              </button>
            </Tooltip>
          </div>
        </header>

        {isHuman && (
          <div className="flex items-center gap-2 border-b border-sky-500/20 bg-sky-500/10 px-5 py-2 text-xs text-sky-200">
            <UserCog size={14} />
            Чат ведёт менеджер. AI молчит
            {conversation?.ai_silent_until
              ? ` до ${timeOf(conversation.ai_silent_until)}`
              : ""}
            .
          </div>
        )}

        <div className="min-h-0 flex-1 scroll-y px-5 py-4">
          {detail.loading && messages.length === 0 ? (
            <SkeletonList rows={5} />
          ) : messages.length === 0 ? (
            <EmptyState
              title="Диалог пуст"
              hint="Напишите первое сообщение от имени клиента — AI ответит и начнёт квалификацию."
            />
          ) : (
            <div className="mx-auto max-w-3xl space-y-3">
              {messages.map((message) => (
                <MessageBubble key={message.id} message={message} />
              ))}
              <div ref={bottomRef} />
            </div>
          )}
        </div>

        <footer className="border-t border-ink-800 bg-ink-900/60 px-5 py-3">
          <div className="mx-auto max-w-3xl">
            <div className="mb-2 flex items-center gap-2">
              <button
                onClick={() => setAsManager(false)}
                className={cx(
                  "chip transition",
                  !asManager
                    ? "border-brand-500/50 bg-brand-500/15 text-brand-200"
                    : "border-ink-600 bg-ink-800 text-slate-400",
                )}
              >
                <User size={11} /> От имени клиента
              </button>
              <button
                onClick={() => setAsManager(true)}
                className={cx(
                  "chip transition",
                  asManager
                    ? "border-sky-500/50 bg-sky-500/15 text-sky-200"
                    : "border-ink-600 bg-ink-800 text-slate-400",
                )}
              >
                <UserCog size={11} /> От имени менеджера
              </button>
              {asManager && (
                <span className="text-[11px] text-slate-500">
                  AI уйдёт в тишину на 30 минут
                </span>
              )}
            </div>
            <div className="flex items-end gap-2">
              <textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void send();
                  }
                }}
                rows={2}
                placeholder={
                  asManager
                    ? "Сообщение менеджера…"
                    : "Напишите как клиент: «Нужен игровой ноут до 100к, я в Москве»"
                }
                className="min-h-[46px] flex-1 resize-none"
              />
              <button className="btn-primary h-[46px] px-4" onClick={() => void send()} disabled={sending}>
                <Send size={15} />
              </button>
            </div>
          </div>
        </footer>
      </section>

      <IntelligencePanel intelligence={detail.data?.intelligence} clockNow={detail.data?.clock.now} />
    </>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isCustomer = message.role === "customer";
  const isManager = message.role === "manager";
  const isFollowUp = message.kind === "followup" || message.kind === "reminder";

  return (
    <div className={cx("flex", isCustomer ? "justify-start" : "justify-end")}>
      <div className={cx("max-w-[78%]", isCustomer ? "" : "text-right")}>
        <div className="mb-1 flex items-center gap-1.5 text-[10px] text-slate-500"
             style={{ justifyContent: isCustomer ? "flex-start" : "flex-end" }}>
          {isCustomer ? (
            <>
              <User size={10} /> Клиент
            </>
          ) : isManager ? (
            <>
              <UserCog size={10} /> {message.author || "Менеджер"}
            </>
          ) : (
            <>
              <Bot size={10} /> AI
              {isFollowUp && (
                <span className="rounded bg-amber-500/15 px-1 text-amber-300">
                  {message.kind === "reminder" ? "напоминание" : "follow-up"}
                </span>
              )}
            </>
          )}
          <span>· {timeOf(message.created_at)}</span>
          {!isCustomer && (
            <span title={message.read_at ? `Прочитано ${timeOf(message.read_at)}` : "Не прочитано"}>
              {message.read_at ? "✓✓" : "✓"}
            </span>
          )}
        </div>
        <div
          className={cx(
            "whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm leading-relaxed text-left",
            isCustomer
              ? "rounded-tl-sm bg-ink-800 text-slate-200"
              : isManager
                ? "rounded-tr-sm bg-sky-600/25 text-sky-50 ring-1 ring-sky-500/30"
                : "rounded-tr-sm bg-brand-600/25 text-slate-100 ring-1 ring-brand-500/25",
          )}
        >
          {message.text}
        </div>
      </div>
    </div>
  );
}

// --- right column ------------------------------------------------------------

function IntelligencePanel({
  intelligence,
  clockNow,
}: {
  intelligence?: Intelligence;
  clockNow?: string;
}) {
  if (!intelligence?.available) {
    return (
      <aside className="hidden w-[330px] shrink-0 border-l border-ink-800 bg-ink-900/40 xl:block">
        <SkeletonList rows={6} />
      </aside>
    );
  }

  return (
    <aside className="hidden w-[330px] shrink-0 flex-col border-l border-ink-800 bg-ink-900/40 xl:flex">
      <div className="border-b border-ink-800 px-4 py-3">
        <div className="flex items-center gap-2">
          <Sparkles size={14} className="text-brand-400" />
          <h3 className="text-sm font-semibold text-slate-100">Live Intelligence</h3>
        </div>
        <p className="mt-0.5 text-[11px] text-slate-500">Состояние обновляется каждым сообщением</p>
      </div>

      <div className="min-h-0 flex-1 scroll-y px-4 py-4 space-y-4">
        {intelligence.handoff.required && (
          <div
            className={cx(
              "rounded-xl border px-3 py-2.5",
              intelligence.handoff.kind === "critical"
                ? "border-rose-500/50 bg-rose-500/10 animate-pulse-ring"
                : "border-amber-500/40 bg-amber-500/10",
            )}
          >
            <p className="flex items-center gap-1.5 text-xs font-semibold text-rose-200">
              <AlertOctagon size={13} />
              {intelligence.handoff.kind === "critical"
                ? "⚠ CRITICAL HANDOFF"
                : "⚠ HUMAN HANDOFF REQUIRED"}
            </p>
            <p className="mt-1 text-[11px] text-slate-300">Reason: {intelligence.handoff.reason}</p>
            {intelligence.handoff.manager && (
              <p className="mt-0.5 text-[11px] text-slate-400">
                Менеджер: {intelligence.handoff.manager}
              </p>
            )}
          </div>
        )}

        <div className="space-y-3">
          <ScoreBar score={intelligence.score} threshold={intelligence.threshold} />
          <div className="flex flex-wrap items-center gap-1.5">
            <TemperatureBadge value={intelligence.temperature} pulse />
            <Badge>{intelligence.closed_count}/{intelligence.total_fields} пунктов</Badge>
            <Badge className={intelligence.qualified ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300" : ""}>
              {intelligence.qualified ? "квалифицирован" : "не квалифицирован"}
            </Badge>
          </div>
        </div>

        <div>
          <p className="section-title mb-2">Параметры квалификации</p>
          <ul className="space-y-1">
            {intelligence.fields.map((field) => (
              <li
                key={field.key}
                className="flex items-start gap-2 rounded-lg bg-ink-850/60 px-2.5 py-1.5"
              >
                <span className={cx("mt-0.5 shrink-0", field.closed ? "text-emerald-400" : "text-slate-600")}>
                  {field.closed ? <CheckCircle2 size={13} /> : <div className="h-3 w-3 rounded-full border border-current" />}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-[11px] text-slate-500">{field.label}</p>
                  <p className={cx("truncate text-xs", field.closed ? "text-slate-100" : "text-slate-600")}>
                    {field.value || "неизвестно"}
                  </p>
                </div>
                <span className="mt-0.5 text-[10px] text-slate-600 tabular-nums">{field.weight}</span>
              </li>
            ))}
          </ul>
        </div>

        {intelligence.hot_signals.length > 0 && (
          <div>
            <p className="section-title mb-2">Сигналы</p>
            <div className="flex flex-wrap gap-1.5">
              {intelligence.hot_signals.map((signal) => (
                <Badge key={signal} className="border-orange-500/40 bg-orange-500/10 text-orange-300">
                  {signal}
                </Badge>
              ))}
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 gap-2">
          <InfoTile label="CRM этап" value={intelligence.stage_label} />
          <InfoTile label="Направление" value={intelligence.direction_label} />
          <InfoTile label="Sentiment" value={intelligence.sentiment} />
          <InfoTile label="Качество" value={intelligence.quality_label} />
        </div>

        <div className="space-y-2">
          <p className="section-title">Контакт</p>
          <div className="flex items-center gap-2 rounded-lg bg-ink-850/60 px-2.5 py-2 text-xs">
            <Phone size={13} className={intelligence.contact_phone ? "text-emerald-400" : "text-slate-600"} />
            <span className={intelligence.contact_phone ? "text-slate-100" : "text-slate-600"}>
              {intelligence.contact_phone || "не получен"}
            </span>
          </div>
        </div>

        {intelligence.products.length > 0 && (
          <div>
            <p className="section-title mb-2">Выбранные модели</p>
            <ul className="space-y-1.5">
              {intelligence.products.map((product) => (
                <li key={product.id} className="rounded-lg bg-ink-850/60 px-2.5 py-2">
                  <p className="truncate text-xs text-slate-100">{product.title}</p>
                  <p className="mt-0.5 flex items-center gap-2 text-[11px] text-slate-500">
                    <span>от {money(product.price)}</span>
                    <span>· {product.condition}</span>
                    <span className={product.stock > 0 ? "text-emerald-400" : "text-rose-400"}>
                      · {product.stock > 0 ? `${product.stock} шт` : "нет"}
                    </span>
                  </p>
                </li>
              ))}
            </ul>
          </div>
        )}

        {intelligence.meeting && (
          <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-2.5">
            <p className="flex items-center gap-1.5 text-xs font-semibold text-emerald-200">
              <MapPin size={13} /> Встреча назначена
            </p>
            <p className="mt-1 text-[11px] text-slate-300">{dateTimeOf(intelligence.meeting.at)}</p>
            <p className="mt-0.5 text-[11px] text-slate-500">{intelligence.meeting.address}</p>
          </div>
        )}

        {intelligence.task && (
          <div className="rounded-xl border border-ink-600 bg-ink-850 px-3 py-2.5">
            <p className="flex items-center gap-1.5 text-xs font-semibold text-slate-200">
              <Timer size={13} /> {intelligence.task.title}
            </p>
            <p className="mt-1 text-[11px] text-slate-400">
              Дедлайн {timeOf(intelligence.task.deadline)} ·{" "}
              <span
                className={
                  intelligence.task.seconds_left <= 0 ? "text-rose-400" : "text-amber-300"
                }
              >
                {countdown(intelligence.task.seconds_left)}
              </span>
            </p>
            {intelligence.task.manager && (
              <p className="mt-0.5 text-[11px] text-slate-500">
                Ответственный: {intelligence.task.manager}
              </p>
            )}
          </div>
        )}

        <div className="rounded-xl border border-brand-500/30 bg-brand-600/10 px-3 py-2.5">
          <p className="section-title text-brand-300">Next best action</p>
          <p className="mt-1 flex items-start gap-1.5 text-xs text-slate-100">
            <ChevronRight size={13} className="mt-0.5 shrink-0 text-brand-400" />
            {intelligence.next_action || "—"}
          </p>
        </div>

        {clockNow && (
          <p className="pt-1 text-center text-[10px] text-slate-600">
            обновлено {timeOf(clockNow)}
          </p>
        )}
      </div>
    </aside>
  );
}

function InfoTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-ink-850/60 px-2.5 py-2">
      <p className="text-[10px] text-slate-500">{label}</p>
      <p className="mt-0.5 truncate text-xs text-slate-100">{value || "—"}</p>
    </div>
  );
}

// --- dialogs -----------------------------------------------------------------

function Modal({ title, subtitle, onClose, children }: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-6 backdrop-blur-sm">
      <Card className="w-full max-w-2xl animate-fade-in">
        <div className="flex items-start justify-between border-b border-ink-700 px-5 py-4">
          <div>
            <h3 className="text-sm font-semibold text-slate-100">{title}</h3>
            {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
          </div>
          <button className="btn-ghost px-2" onClick={onClose}>
            <X size={15} />
          </button>
        </div>
        <div className="max-h-[65vh] scroll-y p-5">{children}</div>
      </Card>
    </div>
  );
}

function ScenarioDialog({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: (conversationId: number) => void;
}) {
  const { data, loading } = usePoll<{ items: ScenarioInfo[] }>(
    () => api.get("/api/live/scenarios"),
    0,
  );
  const [running, setRunning] = useState<string | null>(null);

  const run = async (key: string) => {
    setRunning(key);
    try {
      const result = await api.post<{ conversation_id: number }>(`/api/live/scenarios/${key}`);
      onDone(result.conversation_id);
    } finally {
      setRunning(null);
    }
  };

  return (
    <Modal
      title="Демо-сценарии"
      subtitle="Каждый сценарий проигрывается через реальный pipeline: квалификация, подбор, CRM и правила передачи отрабатывают по-настоящему."
      onClose={onClose}
    >
      {loading ? (
        <SkeletonList rows={4} />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {data?.items.map((scenario) => (
            <button
              key={scenario.key}
              onClick={() => void run(scenario.key)}
              disabled={running !== null}
              className="rounded-xl border border-ink-700 bg-ink-850/60 p-4 text-left transition
                         hover:border-brand-500/50 hover:bg-ink-800 disabled:opacity-50"
            >
              <div className="flex items-start justify-between gap-2">
                <p className="text-sm font-medium text-slate-100">{scenario.title}</p>
                {running === scenario.key ? (
                  <span className="text-[11px] text-brand-300">запуск…</span>
                ) : (
                  <Play size={14} className="mt-0.5 shrink-0 text-brand-400" />
                )}
              </div>
              <p className="mt-1.5 text-xs leading-relaxed text-slate-400">{scenario.description}</p>
              <p className="mt-2 flex items-center gap-1.5 text-[11px] text-slate-500">
                <Sparkles size={11} /> {scenario.expect}
              </p>
              <p className="mt-1 text-[11px] text-slate-600">
                {scenario.customer} · {scenario.steps} сообщения
              </p>
            </button>
          ))}
        </div>
      )}
    </Modal>
  );
}

function NewConversationDialog({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: (conversationId: number) => void;
}) {
  const [name, setName] = useState("");
  const [source, setSource] = useState("МНСГ");
  const [firstMessage, setFirstMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const create = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      const result = await api.post<{ conversation: ConversationSummary }>(
        "/api/live/conversations",
        { name: name.trim(), source, first_message: firstMessage.trim() || null },
      );
      onDone(result.conversation.id);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="Новый тестовый диалог" onClose={onClose}>
      <div className="space-y-4">
        <label className="block space-y-1.5">
          <span className="text-xs font-medium text-slate-400">Имя клиента</span>
          <input value={name} onChange={(e) => setName(e.target.value)} className="w-full" placeholder="Иван" />
        </label>
        <label className="block space-y-1.5">
          <span className="text-xs font-medium text-slate-400">Источник (аккаунт Avito)</span>
          <select value={source} onChange={(e) => setSource(e.target.value)} className="w-full">
            {["МНСГ", "K&V", "NeiroSHOP", "Данил"].map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label className="block space-y-1.5">
          <span className="text-xs font-medium text-slate-400">Первое сообщение (необязательно)</span>
          <textarea
            value={firstMessage}
            onChange={(e) => setFirstMessage(e.target.value)}
            rows={3}
            className="w-full resize-none"
            placeholder="Привет! Нужен игровой ноут до 100к, я в Москве, могу приехать сегодня"
          />
        </label>
        <div className="flex justify-end gap-2">
          <button className="btn-ghost" onClick={onClose}>
            Отмена
          </button>
          <button className="btn-primary" onClick={() => void create()} disabled={busy || !name.trim()}>
            Создать
          </button>
        </div>
      </div>
    </Modal>
  );
}
