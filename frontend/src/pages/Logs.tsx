import { useState } from "react";
import { CheckCircle2, MinusCircle, ShieldCheck, Terminal, XCircle } from "lucide-react";
import { api } from "../lib/api";
import type { ProviderInfo, TurnLogRow } from "../lib/api";
import { usePoll } from "../hooks/usePoll";
import { dateTimeOf, money } from "../lib/format";
import { Badge, Card, EmptyState, ErrorState, Skeleton, cx } from "../components/ui";

interface LogsResponse {
  items: TurnLogRow[];
  provider: ProviderInfo;
  scheduler: Record<string, unknown>;
}

const VERDICT_STYLE: Record<string, string> = {
  PASSED: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  PASSED_WITH_WARNINGS: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  FAILED: "border-rose-500/40 bg-rose-500/10 text-rose-300",
  SKIPPED: "border-slate-600 bg-slate-700/25 text-slate-400",
};

const CHECK_ICON: Record<string, JSX.Element> = {
  passed: <CheckCircle2 size={12} className="text-emerald-400" />,
  warning: <MinusCircle size={12} className="text-amber-400" />,
  failed: <XCircle size={12} className="text-rose-400" />,
  skipped: <MinusCircle size={12} className="text-slate-600" />,
};

export default function Logs() {
  const { data, loading, error } = usePoll<LogsResponse>(
    () => api.get<LogsResponse>("/api/logs?limit=80"),
    5000,
  );
  const [open, setOpen] = useState<number | null>(null);

  if (error) return <div className="p-6"><ErrorState message={error} /></div>;

  return (
    <div className="h-full scroll-y p-6 space-y-5">
      <div>
        <h1 className="flex items-center gap-2 text-lg font-semibold text-slate-100">
          <Terminal size={18} className="text-brand-400" /> Logs / Debug
        </h1>
        <p className="mt-0.5 text-xs text-slate-500">
          Полная трассировка каждого ответа: извлечённые параметры, правила, БЗ, товары, наличие,
          проверка цены, safety-проверки, изменения CRM и задержка модели. Ключи не выводятся.
        </p>
      </div>

      <Card className="flex flex-wrap items-center gap-3 px-5 py-3">
        <Badge className="border-brand-500/40 bg-brand-500/10 text-brand-200">
          LLM: {data?.provider.provider ?? "—"}
        </Badge>
        <span className="font-mono text-[11px] text-slate-500">{data?.provider.model}</span>
        <span className="text-[11px] text-slate-500">{data?.provider.note}</span>
      </Card>

      {loading && !data ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, index) => <Skeleton key={index} className="h-16 w-full" />)}
        </div>
      ) : !data?.items.length ? (
        <EmptyState title="Логов пока нет" hint="Отправьте сообщение в Live Sales." />
      ) : (
        <div className="space-y-2">
          {data.items.map((row) => (
            <Card key={row.id} className="overflow-hidden">
              <button
                onClick={() => setOpen(open === row.id ? null : row.id)}
                className="flex w-full items-start gap-3 px-5 py-3 text-left transition hover:bg-ink-850/40"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-medium text-slate-200">{row.customer}</span>
                    <Badge className={VERDICT_STYLE[row.guard_verdict] ?? ""}>
                      <ShieldCheck size={10} /> {row.guard_verdict}
                    </Badge>
                    <span className="text-[10px] text-slate-600">
                      {dateTimeOf(row.created_at)} · {row.latency_ms} мс · {row.provider}
                    </span>
                  </div>
                  <p className="mt-1 truncate text-[11px] text-slate-500">
                    <span className="text-slate-400">→</span> {row.customer_message || "—"}
                  </p>
                  <p className="truncate text-[11px] text-slate-500">
                    <span className="text-brand-400">←</span> {row.ai_response || "—"}
                  </p>
                </div>
                <span className="mt-1 shrink-0 text-[10px] text-slate-600">#{row.id}</span>
              </button>

              {open === row.id && (
                <div className="grid gap-4 border-t border-ink-800 bg-ink-950/40 p-5 lg:grid-cols-2">
                  <Block title="Сообщение клиента">
                    <p className="whitespace-pre-wrap text-xs text-slate-300">{row.customer_message || "—"}</p>
                  </Block>
                  <Block title="Ответ AI">
                    <p className="whitespace-pre-wrap text-xs text-slate-300">{row.ai_response || "—"}</p>
                  </Block>

                  <Block title="Извлечённая квалификация">
                    {Object.keys(row.extracted).length === 0 ? (
                      <Empty />
                    ) : (
                      <ul className="space-y-1">
                        {Object.entries(row.extracted).map(([key, value]) => (
                          <li key={key} className="flex gap-2 text-xs">
                            <span className="w-24 shrink-0 text-slate-500">{key}</span>
                            <span className="text-slate-200">
                              {Array.isArray(value) ? value.join(", ") : String(value)}
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </Block>

                  <Block title="Сработавшие правила">
                    {row.rules_triggered.length === 0 ? (
                      <Empty />
                    ) : (
                      <div className="flex flex-wrap gap-1.5">
                        {row.rules_triggered.map((rule) => (
                          <Badge key={rule} className="font-mono text-[10px]">{rule}</Badge>
                        ))}
                      </div>
                    )}
                  </Block>

                  <Block title="Фрагменты базы знаний">
                    {row.kb_fragments.length === 0 ? (
                      <Empty />
                    ) : (
                      <ul className="space-y-1.5">
                        {row.kb_fragments.map((fragment, index) => (
                          <li key={index} className="rounded bg-ink-850 px-2.5 py-1.5">
                            <p className="text-[11px] text-slate-200">
                              {fragment.title}{" "}
                              <span className="text-slate-600">
                                ({fragment.branch_label} v{fragment.version})
                              </span>
                            </p>
                          </li>
                        ))}
                      </ul>
                    )}
                  </Block>

                  <Block title="Снимок наличия на момент ответа">
                    {row.inventory_snapshot.length === 0 ? (
                      <Empty />
                    ) : (
                      <ul className="space-y-1">
                        {row.inventory_snapshot.map((item, index) => (
                          <li key={index} className="flex items-center gap-2 text-xs">
                            <span className="font-mono text-[10px] text-slate-600">{item.sku}</span>
                            <span className="flex-1 truncate text-slate-300">{item.title}</span>
                            <span className="text-slate-500">от {money(item.price)}</span>
                            <span className={item.stock > 0 ? "text-emerald-400" : "text-rose-400"}>
                              {item.stock > 0 ? `${item.stock} шт` : "нет"}
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </Block>

                  <Block title="Проверка цены">
                    <pre className="overflow-x-auto whitespace-pre-wrap font-mono text-[10px] text-slate-400">
                      {JSON.stringify(row.price_validation, null, 2)}
                    </pre>
                  </Block>

                  <Block title="Изменения CRM">
                    {row.crm_mutations.length === 0 ? (
                      <Empty />
                    ) : (
                      <ul className="space-y-1">
                        {row.crm_mutations.map((mutation, index) => (
                          <li key={index} className="text-xs text-slate-300">
                            <span className="text-slate-500">{mutation.field}:</span>{" "}
                            {String(mutation.from)} → <span className="text-slate-100">{String(mutation.to)}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </Block>

                  <div className="lg:col-span-2">
                    <Block title={`Response validation: ${row.guard_verdict}`}>
                      <ul className="grid gap-1 sm:grid-cols-2">
                        {row.safety_checks.map((check) => (
                          <li key={check.code} className="flex items-start gap-2 text-xs">
                            <span className="mt-0.5 shrink-0">{CHECK_ICON[check.status]}</span>
                            <span className="min-w-0">
                              <span
                                className={cx(
                                  check.status === "failed"
                                    ? "text-rose-300"
                                    : check.status === "warning"
                                      ? "text-amber-300"
                                      : "text-slate-300",
                                )}
                              >
                                {check.label}
                              </span>
                              {check.detail && (
                                <span className="block text-[10px] text-slate-600">{check.detail}</span>
                              )}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </Block>
                  </div>

                  {(row.handoff_reason || row.error) && (
                    <div className="lg:col-span-2 space-y-2">
                      {row.handoff_reason && (
                        <p className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
                          Handoff: {row.handoff_reason}
                        </p>
                      )}
                      {row.error && (
                        <p className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                          Ошибка: {row.error}
                        </p>
                      )}
                    </div>
                  )}
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-ink-800 bg-ink-900/60 p-3.5">
      <p className="section-title mb-2">{title}</p>
      {children}
    </div>
  );
}

function Empty() {
  return <p className="text-[11px] text-slate-600">—</p>;
}
