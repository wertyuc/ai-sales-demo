import { useEffect, useState } from "react";
import { History, RotateCcw, Save, Sliders } from "lucide-react";
import { api } from "../lib/api";
import type { ProviderInfo } from "../lib/api";
import { usePoll } from "../hooks/usePoll";
import { dateTimeOf } from "../lib/format";
import { Badge, Card, CardHeader, EmptyState, Field, Skeleton, Toggle, cx } from "../components/ui";

type Section = Record<string, unknown>;

interface SettingsResponse {
  sections: Record<string, Section>;
  labels: Record<string, string>;
  defaults: Record<string, Section>;
  provider: ProviderInfo;
  adapters: Record<string, string>;
}

interface AuditRow {
  id: number;
  at: string;
  actor: string;
  entity: string;
  field: string;
  old: string;
  new: string;
}

const ORDER = ["qualification", "handoff", "followup", "meeting", "ai_style", "sales"];

const HINTS: Record<string, string> = {
  qualification: "Поля, веса и пороги. Формула процента — конфигурация, а не константа в промпте.",
  handoff: "Правила обязательной передачи менеджеру (§26) и параметры задачи.",
  followup: "Тайминги повторных касаний и приоритетные окна (§12, §13).",
  meeting: "Напоминания о встрече и режим работы офиса (§11).",
  ai_style: "Как ассистент разговаривает: длина, тон, эмодзи, подстройка под клиента.",
  sales: "Цены, промокод, адрес офиса, количество предлагаемых вариантов.",
};

const FIELD_LABELS: Record<string, string> = {
  formula: "Формула процента",
  qualified_min_fields: "Минимум пунктов для квалификации",
  handoff_threshold: "Порог автопередачи, %",
  region_min_fields: "Пунктов для правила «регион»",
  partial_counts: "Засчитывать частичные ответы",
  negative: "Негатив клиента",
  phone_request: "Просьба позвонить",
  ai_suspicion: "Подозрение, что это AI",
  region_rule: "Регион + N пунктов",
  photo_video: "Запрос фото/видео",
  qualification_threshold: "Квалификация ≥ порога",
  service_questions: "Сервисные вопросы",
  ai_silence_minutes: "Тишина AI после менеджера, мин",
  task_deadline_minutes: "Дедлайн задачи, мин",
  task_title: "Название задачи",
  enabled: "Включено",
  require_read: "Только если сообщение прочитано",
  first_delay_minutes: "1-е касание, мин",
  second_delay_minutes: "2-е касание, мин",
  evening_hour: "Вечернее касание, час",
  max_touches_per_day: "Максимум касаний в сутки",
  max_unread_touches: "Максимум касаний без прочтения",
  windows: "Приоритетные окна",
  respect_windows_from_attempt: "Учитывать окна с попытки №",
  reminder_day_before: "Напомнить за день",
  reminder_morning_hour: "Утреннее напоминание, час",
  reminder_hours_before: "Напомнить за N часов",
  office_open: "Офис открывается",
  office_close: "Офис закрывается",
  verbosity: "Длина ответа",
  tone: "Тон",
  emoji: "Эмодзи",
  max_sentences: "Максимум предложений",
  mirror_customer_style: "Подстраиваться под стиль клиента",
  greeting_mirroring: "Зеркалить приветствие",
  price_prefix: "Префикс цены",
  never_above_listing: "Не выше цены объявления",
  price_policy: "Когда называть цену",
  promo_code: "Промокод",
  promo_enabled: "Выдавать промокод",
  office_address: "Адрес офиса",
  office_hours: "Режим работы",
  delivery_regions: "Доставка в регионы",
  max_offers: "Максимум вариантов",
  min_offers: "Минимум вариантов",
  gift_conditions: "Состояния для подарка",
};

const ENUMS: Record<string, string[]> = {
  formula: ["weighted", "ratio"],
  verbosity: ["short", "detailed"],
  tone: ["casual", "formal"],
  price_policy: ["always", "second_request"],
};

export default function ControlCenter() {
  const { data, loading, refresh } = usePoll<SettingsResponse>(
    () => api.get<SettingsResponse>("/api/control/settings"),
    0,
  );
  const audit = usePoll<{ items: AuditRow[] }>(() => api.get("/api/control/audit?limit=60"), 0);
  const [active, setActive] = useState("qualification");
  const [draft, setDraft] = useState<Section | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setDraft(null);
    setSaved(false);
  }, [active]);

  const section = data?.sections[active];
  const values = draft ?? section ?? {};
  const dirty = draft !== null;

  const update = (key: string, value: unknown) => {
    setDraft({ ...(draft ?? section ?? {}), [key]: value });
    setSaved(false);
  };

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      await api.put(`/api/control/settings/${active}`, { values: draft });
      setDraft(null);
      setSaved(true);
      await refresh();
      await audit.refresh();
    } finally {
      setSaving(false);
    }
  };

  const reset = async () => {
    await api.post(`/api/control/settings/${active}/reset`);
    setDraft(null);
    await refresh();
    await audit.refresh();
  };

  return (
    <div className="h-full scroll-y p-6 space-y-5">
      <div>
        <h1 className="flex items-center gap-2 text-lg font-semibold text-slate-100">
          <Sliders size={18} className="text-brand-400" /> AI Control Center
        </h1>
        <p className="mt-0.5 text-xs text-slate-500">
          Правила меняются здесь и применяются к следующему сообщению — без правки кода и промпта.
        </p>
      </div>

      <div className="grid gap-5 lg:grid-cols-[220px_1fr]">
        <nav className="space-y-1">
          {ORDER.map((key) => (
            <button
              key={key}
              onClick={() => setActive(key)}
              className={cx(
                "w-full rounded-lg px-3 py-2 text-left text-sm transition",
                active === key
                  ? "bg-brand-600/15 text-brand-200 ring-1 ring-brand-500/25"
                  : "text-slate-400 hover:bg-ink-800 hover:text-slate-200",
              )}
            >
              {data?.labels[key] ?? key}
            </button>
          ))}
        </nav>

        <div className="space-y-5">
          <Card>
            <CardHeader
              title={data?.labels[active] ?? active}
              subtitle={HINTS[active]}
              right={
                <div className="flex items-center gap-2">
                  {saved && <span className="text-[11px] text-emerald-400">сохранено</span>}
                  <button className="btn-ghost" onClick={() => void reset()}>
                    <RotateCcw size={14} /> По умолчанию
                  </button>
                  <button className="btn-primary" onClick={() => void save()} disabled={!dirty || saving}>
                    <Save size={14} /> Сохранить
                  </button>
                </div>
              }
            />
            <div className="p-5">
              {loading && !data ? (
                <div className="space-y-3">
                  {Array.from({ length: 5 }).map((_, index) => (
                    <Skeleton key={index} className="h-10 w-full" />
                  ))}
                </div>
              ) : active === "qualification" ? (
                <QualificationEditor values={values} onChange={update} />
              ) : (
                <div className="grid gap-x-8 gap-y-1 sm:grid-cols-2">
                  {Object.entries(values).map(([key, value]) => (
                    <SettingControl
                      key={key}
                      name={key}
                      value={value}
                      onChange={(next) => update(key, next)}
                    />
                  ))}
                </div>
              )}
            </div>
          </Card>

          <Card>
            <CardHeader
              title="Журнал изменений"
              subtitle="Кто, что и когда изменил — со старым и новым значением (§35)"
              icon={<History size={15} />}
            />
            {!audit.data?.items.length ? (
              <EmptyState title="Изменений пока не было" hint="Измените любое правило выше." />
            ) : (
              <ul className="max-h-[380px] divide-y divide-ink-800/70 scroll-y">
                {audit.data.items.map((row) => (
                  <li key={row.id} className="px-5 py-2.5">
                    <div className="flex items-center gap-2">
                      <Badge>{row.entity}</Badge>
                      <span className="text-xs text-slate-200">
                        {FIELD_LABELS[row.field] ?? row.field}
                      </span>
                      <span className="ml-auto text-[10px] text-slate-600">{dateTimeOf(row.at)}</span>
                    </div>
                    <p className="mt-1 text-[11px] text-slate-500">
                      <span className="line-through opacity-70">{row.old || "—"}</span>
                      {" → "}
                      <span className="text-slate-300">{row.new}</span>
                      <span className="ml-2 text-slate-600">· {row.actor}</span>
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

function SettingControl({
  name,
  value,
  onChange,
}: {
  name: string;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const label = FIELD_LABELS[name] ?? name;

  if (typeof value === "boolean") {
    return <Toggle checked={value} onChange={onChange} label={label} />;
  }
  if (Array.isArray(value)) {
    return (
      <div className="py-2">
        <Field label={label} hint="через запятую">
          <input
            className="w-full"
            value={value.join(", ")}
            onChange={(event) =>
              onChange(
                event.target.value
                  .split(",")
                  .map((part) => part.trim())
                  .filter(Boolean),
              )
            }
          />
        </Field>
      </div>
    );
  }
  if (ENUMS[name]) {
    return (
      <div className="py-2">
        <Field label={label}>
          <select className="w-full" value={String(value)} onChange={(event) => onChange(event.target.value)}>
            {ENUMS[name].map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </Field>
      </div>
    );
  }
  if (typeof value === "number") {
    return (
      <div className="py-2">
        <Field label={label}>
          <input
            type="number"
            className="w-full"
            value={value}
            onChange={(event) => onChange(Number(event.target.value))}
          />
        </Field>
      </div>
    );
  }
  return (
    <div className="py-2">
      <Field label={label}>
        <input className="w-full" value={String(value ?? "")} onChange={(event) => onChange(event.target.value)} />
      </Field>
    </div>
  );
}

function QualificationEditor({
  values,
  onChange,
}: {
  values: Section;
  onChange: (key: string, value: unknown) => void;
}) {
  const fields = (values.fields as { key: string; label: string; weight: number; enabled: boolean }[]) ?? [];
  const totalWeight = fields.filter((f) => f.enabled).reduce((sum, f) => sum + f.weight, 0);

  const patchField = (index: number, patch: Partial<(typeof fields)[number]>) => {
    const next = fields.map((field, i) => (i === index ? { ...field, ...patch } : field));
    onChange("fields", next);
  };

  return (
    <div className="space-y-5">
      <div>
        <div className="mb-2 flex items-center justify-between">
          <p className="section-title">Поля квалификации и веса</p>
          <span
            className={cx(
              "text-[11px] tabular-nums",
              totalWeight === 100 ? "text-slate-500" : "text-amber-400",
            )}
          >
            сумма весов: {totalWeight}
          </span>
        </div>
        <ul className="space-y-1.5">
          {fields.map((field, index) => (
            <li key={field.key} className="flex items-center gap-3 rounded-lg bg-ink-850 px-3 py-2">
              <button
                onClick={() => patchField(index, { enabled: !field.enabled })}
                className={cx(
                  "h-4 w-4 shrink-0 rounded border transition",
                  field.enabled ? "border-brand-500 bg-brand-600" : "border-ink-500",
                )}
                title={field.enabled ? "Отключить параметр" : "Включить параметр"}
              />
              <span className={cx("flex-1 text-sm", field.enabled ? "text-slate-200" : "text-slate-600")}>
                {field.label}
              </span>
              <input
                type="range"
                min={0}
                max={40}
                value={field.weight}
                onChange={(event) => patchField(index, { weight: Number(event.target.value) })}
                className="w-40 accent-indigo-500"
              />
              <span className="w-8 text-right text-xs tabular-nums text-slate-300">{field.weight}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="grid gap-x-8 gap-y-1 sm:grid-cols-2">
        {Object.entries(values)
          .filter(([key]) => key !== "fields")
          .map(([key, value]) => (
            <SettingControl key={key} name={key} value={value} onChange={(next) => onChange(key, next)} />
          ))}
      </div>

      <p className="rounded-lg bg-ink-850 px-3 py-2 text-[11px] text-slate-500">
        При формуле <span className="font-mono text-slate-400">weighted</span> процент считается как
        сумма весов закрытых полей / сумму весов включённых полей. При{" "}
        <span className="font-mono text-slate-400">ratio</span> — просто доля закрытых полей.
      </p>
    </div>
  );
}
