import { BrainCircuit, FlaskConical, Lightbulb, ShieldQuestion } from "lucide-react";
import { api } from "../lib/api";
import type { Insights as InsightsData } from "../lib/api";
import { usePoll } from "../hooks/usePoll";
import { dateTimeOf } from "../lib/format";
import { Badge, Card, CardHeader, EmptyState, ErrorState, Skeleton, cx } from "../components/ui";

const SEVERITY: Record<string, { label: string; className: string }> = {
  high: { label: "высокий приоритет", className: "border-rose-500/40 bg-rose-500/10 text-rose-300" },
  medium: { label: "средний", className: "border-amber-500/40 bg-amber-500/10 text-amber-300" },
  low: { label: "низкий", className: "border-slate-600 bg-slate-700/25 text-slate-300" },
};

const CONFIDENCE: Record<string, string> = {
  high: "высокая достоверность",
  medium: "средняя достоверность",
  low: "слабый сигнал",
};

export default function Insights() {
  const { data, loading, error } = usePoll<InsightsData>(
    () => api.get<InsightsData>("/api/analytics/insights"),
    20000,
  );

  if (error) return <div className="p-6"><ErrorState message={error} /></div>;

  return (
    <div className="h-full scroll-y p-6 space-y-5">
      <div>
        <h1 className="flex items-center gap-2 text-lg font-semibold text-slate-100">
          <BrainCircuit size={18} className="text-brand-400" /> AI Insights
        </h1>
        <p className="mt-0.5 text-xs text-slate-500">
          Самоанализ работы ассистента: где теряются клиенты, где передача была поздней,
          что повышает конверсию.
        </p>
      </div>

      <Card className="flex flex-wrap items-center gap-3 px-5 py-3.5">
        <Badge className="border-brand-500/40 bg-brand-500/10 text-brand-200">
          <FlaskConical size={11} /> {data?.dataset.label ?? "Demo dataset insight"}
        </Badge>
        <span className="text-xs text-slate-400">
          выборка: {data?.dataset.leads ?? 0} диалогов, {data?.dataset.turns ?? 0} ответов AI
        </span>
        <span className="ml-auto text-[11px] text-slate-600">
          рассчитано {dateTimeOf(data?.generated_at)}
        </span>
      </Card>

      <div className="flex items-start gap-2 rounded-xl border border-amber-500/25 bg-amber-500/5 px-4 py-3 text-xs text-amber-200/90">
        <ShieldQuestion size={15} className="mt-0.5 shrink-0" />
        <p>{data?.dataset.note}</p>
      </div>

      {loading && !data ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-28 w-full" />
          ))}
        </div>
      ) : !data?.findings.length ? (
        <EmptyState
          title="Наблюдений пока нет"
          hint="Проиграйте несколько сценариев в Live Sales — анализ появится автоматически."
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {data.findings.map((finding) => {
            const severity = SEVERITY[finding.severity] ?? SEVERITY.low;
            return (
              <Card key={finding.id} className="p-5 card-hover">
                <div className="flex items-start justify-between gap-3">
                  <h3 className="text-sm font-semibold leading-snug text-slate-100">
                    {finding.title}
                  </h3>
                  <Badge className={cx("shrink-0", severity.className)}>{severity.label}</Badge>
                </div>
                <p className="mt-2 text-xs leading-relaxed text-slate-400">{finding.detail}</p>
                <div className="mt-3 flex items-start gap-2 rounded-lg bg-brand-600/10 px-3 py-2 ring-1 ring-brand-500/20">
                  <Lightbulb size={13} className="mt-0.5 shrink-0 text-brand-300" />
                  <p className="text-xs text-slate-200">{finding.recommendation}</p>
                </div>
                <div className="mt-3 flex items-center gap-2 text-[11px] text-slate-600">
                  <span>выборка: {finding.sample}</span>
                  <span>·</span>
                  <span>{CONFIDENCE[finding.confidence] ?? finding.confidence}</span>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {data?.recommendations.length ? (
        <Card>
          <CardHeader
            title="Предложения на согласование"
            subtitle="Самообучение по циклу: анализ → рекомендация → согласование → изменение БЗ → замер (§38)"
          />
          <ul className="divide-y divide-ink-800/70">
            {data.recommendations.map((recommendation) => (
              <li key={recommendation.id} className="flex items-start gap-3 px-5 py-3">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-400" />
                <div className="min-w-0 flex-1">
                  <p className="text-xs text-slate-200">{recommendation.text}</p>
                  <p className="mt-0.5 text-[11px] text-slate-600">
                    основано на {recommendation.based_on}
                  </p>
                </div>
                <Badge className="shrink-0">ожидает согласования</Badge>
              </li>
            ))}
          </ul>
          <p className="border-t border-ink-800 px-5 py-2.5 text-[11px] text-slate-600">
            AI не меняет рабочие правила самостоятельно — изменения вносятся в Control Center
            после согласования, с записью в журнал изменений.
          </p>
        </Card>
      ) : null}
    </div>
  );
}
