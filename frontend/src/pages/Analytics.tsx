import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as RTooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Clock3,
  Flame,
  HandCoins,
  MessageSquareWarning,
  Percent,
  Target,
  TrendingUp,
  Users,
} from "lucide-react";
import { api } from "../lib/api";
import type { Analytics as AnalyticsData } from "../lib/api";
import { usePoll } from "../hooks/usePoll";
import { CHART_COLORS, CHART_GRID, compactMoney, dayOf } from "../lib/format";
import { Card, CardHeader, EmptyState, ErrorState, Skeleton, Stat } from "../components/ui";

interface DailyReport {
  date: string;
  leads_total: number;
  leads_by_source: Record<string, number>;
  handed_to_managers: number;
  qualified_total: number;
  qualified_by_source: Record<string, number>;
  quality_total: number;
  quality_by_source: Record<string, number>;
  poor: number;
  negative: number;
  ignored: number;
  arrived: number;
}

const tooltipStyle = {
  contentStyle: {
    background: "#111527",
    border: "1px solid #2a3149",
    borderRadius: 10,
    fontSize: 12,
  },
  labelStyle: { color: "#e2e8f0" },
  itemStyle: { color: "#cbd5e1" },
};

export default function Analytics() {
  const { data, loading, error } = usePoll<AnalyticsData>(
    () => api.get<AnalyticsData>("/api/analytics/overview?days=30"),
    10000,
  );
  const daily = usePoll<DailyReport>(() => api.get<DailyReport>("/api/analytics/daily"), 20000);

  if (error) {
    return (
      <div className="p-6">
        <ErrorState message={error} />
      </div>
    );
  }

  if (loading && !data) {
    return (
      <div className="grid gap-4 p-6 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 8 }).map((_, index) => (
          <Skeleton key={index} className="h-24 w-full" />
        ))}
      </div>
    );
  }
  if (!data) return null;

  const { totals, rates, response } = data;

  return (
    <div className="h-full scroll-y p-6 space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-slate-100">Analytics</h1>
        <p className="mt-0.5 text-xs text-slate-500">
          За 30 дней · рассчитано по демо-базе, обновляется вместе с диалогами
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Лидов" value={totals.leads} icon={<Users size={15} />} />
        <Stat
          label="Квалификация"
          value={`${rates.qualification_rate}%`}
          hint={`${totals.qualified_3} лидов ≥3 пунктов`}
          tone={rates.qualification_rate >= 60 ? "good" : "warn"}
          icon={<Target size={15} />}
        />
        <Stat
          label="Получено контактов"
          value={totals.contacts}
          hint={`конверсия ${rates.qualification_to_contact}%`}
          tone="brand"
          icon={<Percent size={15} />}
        />
        <Stat
          label="Продажи"
          value={totals.sales}
          hint={totals.revenue ? compactMoney(totals.revenue) : "—"}
          tone="good"
          icon={<HandCoins size={15} />}
        />
        <Stat
          label="Первый ответ ≤2 мин"
          value={`${rates.first_response_under_2min}%`}
          hint={`среднее ${response.avg_seconds} с`}
          tone={rates.first_response_under_2min >= 90 ? "good" : "warn"}
          icon={<Clock3 size={15} />}
        />
        <Stat
          label="Передано менеджерам"
          value={totals.handoffs}
          hint={`сервис: ${totals.service_handoffs}`}
          icon={<TrendingUp size={15} />}
        />
        <Stat
          label="Негатив / игнор"
          value={`${totals.negative} / ${totals.ignored}`}
          tone={totals.negative > 0 ? "bad" : "default"}
          icon={<MessageSquareWarning size={15} />}
        />
        <Stat
          label="Встречи / приходы"
          value={`${totals.meetings} / ${totals.arrived}`}
          hint={`доход до встречи ${rates.contact_to_meeting}%`}
          icon={<Flame size={15} />}
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader title="Воронка" subtitle="От первого сообщения до продажи" />
          <div className="p-4">
            {data.funnel.every((step) => step.value === 0) ? (
              <EmptyState title="Данных пока нет" />
            ) : (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart
                  data={data.funnel}
                  layout="vertical"
                  margin={{ left: 8, right: 44, top: 4, bottom: 4 }}
                >
                  <CartesianGrid stroke={CHART_GRID} horizontal={false} />
                  <XAxis type="number" tickLine={false} axisLine={false} />
                  <YAxis
                    type="category"
                    dataKey="label"
                    width={150}
                    tickLine={false}
                    axisLine={false}
                  />
                  <RTooltip {...tooltipStyle} cursor={{ fill: "rgba(148,163,184,.06)" }} />
                  <Bar dataKey="value" radius={[0, 4, 4, 0]} barSize={18} label={{
                    position: "right",
                    fill: "#cbd5e1",
                    fontSize: 11,
                  }}>
                    {data.funnel.map((_, index) => (
                      <Cell key={index} fill={CHART_COLORS[0]} fillOpacity={1 - index * 0.13} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </Card>

        <Card>
          <CardHeader title="Динамика" subtitle="Лиды, передачи и встречи по дням" />
          <div className="p-4">
            {data.timeline.length === 0 ? (
              <EmptyState title="Недостаточно истории" />
            ) : (
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={data.timeline} margin={{ left: -18, right: 12, top: 6, bottom: 4 }}>
                  <CartesianGrid stroke={CHART_GRID} />
                  <XAxis dataKey="date" tickFormatter={dayOf} tickLine={false} axisLine={false} minTickGap={24} />
                  <YAxis tickLine={false} axisLine={false} allowDecimals={false} />
                  <RTooltip {...tooltipStyle} labelFormatter={(value) => dayOf(String(value))} />
                  <Legend wrapperStyle={{ fontSize: 11, paddingTop: 8 }} iconType="plainline" />
                  <Line
                    type="monotone"
                    dataKey="leads"
                    name="Лиды"
                    stroke={CHART_COLORS[0]}
                    strokeWidth={2}
                    dot={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="handoffs"
                    name="Передачи"
                    stroke={CHART_COLORS[1]}
                    strokeWidth={2}
                    dot={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="meetings"
                    name="Встречи"
                    stroke={CHART_COLORS[2]}
                    strokeWidth={2}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </Card>

        <Card>
          <CardHeader title="Причины передачи менеджеру" subtitle="Какие правила срабатывают чаще" />
          <div className="p-4">
            {data.handoff_reasons.length === 0 ? (
              <EmptyState title="Передач пока не было" />
            ) : (
              <ResponsiveContainer width="100%" height={230}>
                <BarChart
                  data={data.handoff_reasons}
                  layout="vertical"
                  margin={{ left: 8, right: 40, top: 4, bottom: 4 }}
                >
                  <CartesianGrid stroke={CHART_GRID} horizontal={false} />
                  <XAxis type="number" tickLine={false} axisLine={false} allowDecimals={false} />
                  <YAxis type="category" dataKey="label" width={170} tickLine={false} axisLine={false} />
                  <RTooltip {...tooltipStyle} cursor={{ fill: "rgba(148,163,184,.06)" }} />
                  <Bar
                    dataKey="value"
                    fill={CHART_COLORS[1]}
                    radius={[0, 4, 4, 0]}
                    barSize={16}
                    label={{ position: "right", fill: "#cbd5e1", fontSize: 11 }}
                  />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </Card>

        <Card>
          <CardHeader title="Качество заявок" subtitle="Классификация по правилам §41" />
          <div className="p-4">
            {data.quality.length === 0 ? (
              <EmptyState title="Данных пока нет" />
            ) : (
              <ResponsiveContainer width="100%" height={230}>
                <BarChart
                  data={data.quality}
                  layout="vertical"
                  margin={{ left: 8, right: 40, top: 4, bottom: 4 }}
                >
                  <CartesianGrid stroke={CHART_GRID} horizontal={false} />
                  <XAxis type="number" tickLine={false} axisLine={false} allowDecimals={false} />
                  <YAxis type="category" dataKey="label" width={150} tickLine={false} axisLine={false} />
                  <RTooltip {...tooltipStyle} cursor={{ fill: "rgba(148,163,184,.06)" }} />
                  <Bar
                    dataKey="value"
                    fill={CHART_COLORS[2]}
                    radius={[0, 4, 4, 0]}
                    barSize={16}
                    label={{ position: "right", fill: "#cbd5e1", fontSize: 11 }}
                  />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </Card>
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title="Конверсии по этапам" subtitle="Сквозная воронка §40" />
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-b-xl bg-ink-800 sm:grid-cols-3">
            {[
              ["Лид → квалификация", rates.lead_to_qualification],
              ["Квалификация → контакт", rates.qualification_to_contact],
              ["Контакт → встреча", rates.contact_to_meeting],
              ["Встреча → приход", rates.meeting_to_arrival],
              ["Лид → продажа", rates.lead_to_sale],
              ["Первый ответ ≤2 мин", rates.first_response_under_2min],
            ].map(([label, value]) => (
              <div key={String(label)} className="bg-ink-900 px-4 py-3.5">
                <p className="text-[11px] text-slate-500">{label}</p>
                <p className="mt-1 text-xl font-semibold text-slate-100 tabular-nums">{value}%</p>
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <CardHeader title="Источники" subtitle="Аккаунты Avito" />
          <div className="p-4">
            {data.sources.length === 0 ? (
              <EmptyState title="Нет данных" />
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-[11px] uppercase text-slate-500">
                    <th className="pb-2 font-medium">Источник</th>
                    <th className="pb-2 text-right font-medium">Лиды</th>
                    <th className="pb-2 text-right font-medium">Квал.</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-800/70">
                  {data.sources.map((row) => (
                    <tr key={row.source}>
                      <td className="py-2 text-slate-200">{row.source}</td>
                      <td className="py-2 text-right tabular-nums text-slate-300">{row.leads}</td>
                      <td className="py-2 text-right tabular-nums text-slate-400">
                        {row.qualified} <span className="text-slate-600">({row.rate}%)</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </Card>
      </div>

      <Card>
        <CardHeader
          title={`Ежедневный отчёт · ${daily.data?.date ?? ""}`}
          subtitle="Формат из §39 технического задания"
        />
        <div className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-4">
          <ReportBlock title="📊 Лиды пришли" total={daily.data?.leads_total} rows={daily.data?.leads_by_source} />
          <ReportBlock
            title="✅ Квалифицированные"
            total={daily.data?.qualified_total}
            rows={daily.data?.qualified_by_source}
          />
          <ReportBlock
            title="✅ Качественные заявки"
            total={daily.data?.quality_total}
            rows={daily.data?.quality_by_source}
          />
          <div className="space-y-1.5 rounded-lg bg-ink-850 p-3.5 text-xs">
            <p className="section-title">Итоги дня</p>
            <p className="text-slate-300">
              Передала в работу: <span className="text-slate-100">{daily.data?.handed_to_managers ?? 0}</span>
            </p>
            <p className="text-slate-300">
              ❌ Некачественные: <span className="text-slate-100">{daily.data?.poor ?? 0}</span>
            </p>
            <p className="text-slate-300">
              ❌ Негативные: <span className="text-slate-100">{daily.data?.negative ?? 0}</span>
            </p>
            <p className="text-slate-300">
              💤 Игнор: <span className="text-slate-100">{daily.data?.ignored ?? 0}</span>
            </p>
            <p className="text-slate-300">
              🤝 Пришедшие в магазин: <span className="text-slate-100">{daily.data?.arrived ?? 0}</span>
            </p>
          </div>
        </div>
      </Card>

      {data.top_products.length > 0 && (
        <Card>
          <CardHeader title="Чаще всего предлагаемые модели" subtitle="Что AI подбирает клиентам" />
          <ul className="divide-y divide-ink-800/70">
            {data.top_products.map((product) => (
              <li key={product.sku} className="flex items-center justify-between px-5 py-2.5 text-sm">
                <span className="text-slate-200">{product.title}</span>
                <span className="flex items-center gap-4 text-[11px] text-slate-500">
                  <span>от {compactMoney(product.price)}</span>
                  <span className="tabular-nums text-slate-300">{product.value} раз</span>
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

function ReportBlock({
  title,
  total,
  rows,
}: {
  title: string;
  total?: number;
  rows?: Record<string, number>;
}) {
  return (
    <div className="rounded-lg bg-ink-850 p-3.5">
      <p className="section-title">{title}</p>
      <p className="mt-1 text-2xl font-semibold text-slate-100 tabular-nums">{total ?? 0}</p>
      <ul className="mt-2 space-y-0.5 text-[11px] text-slate-400">
        {Object.entries(rows ?? {}).map(([source, value]) => (
          <li key={source} className="flex justify-between">
            <span>{source}</span>
            <span className="tabular-nums text-slate-300">{value}</span>
          </li>
        ))}
        {!rows || Object.keys(rows).length === 0 ? <li className="text-slate-600">нет данных</li> : null}
      </ul>
    </div>
  );
}
