import { useEffect, useState } from "react";
import { BookOpen, History, Plus, RotateCcw, Save, X } from "lucide-react";
import { api } from "../lib/api";
import type { KBArticleRow } from "../lib/api";
import { usePoll } from "../hooks/usePoll";
import { dateTimeOf } from "../lib/format";
import { Badge, Card, EmptyState, Field, Skeleton, Toggle, cx } from "../components/ui";

interface KBResponse {
  branches: { key: string; label: string }[];
  items: KBArticleRow[];
}

interface RevisionRow {
  version: number;
  title: string;
  body: string;
  enabled: boolean;
  author: string;
  at: string;
}

export default function KnowledgeBase() {
  const { data, loading, refresh } = usePoll<KBResponse>(() => api.get<KBResponse>("/api/kb"), 0);
  const [branch, setBranch] = useState<string>("");
  const [selected, setSelected] = useState<number | null>(null);
  const [draft, setDraft] = useState<{ title: string; body: string } | null>(null);
  const [showRevisions, setShowRevisions] = useState(false);
  const [creating, setCreating] = useState(false);

  const items = (data?.items ?? []).filter((item) => !branch || item.branch === branch);
  const article = data?.items.find((item) => item.id === selected) ?? null;

  useEffect(() => {
    if (selected === null && items.length) setSelected(items[0].id);
  }, [items, selected]);

  useEffect(() => {
    setDraft(null);
    setShowRevisions(false);
  }, [selected]);

  const save = async () => {
    if (!article || !draft) return;
    await api.put(`/api/kb/${article.id}`, draft);
    setDraft(null);
    await refresh();
  };

  const toggleEnabled = async (row: KBArticleRow) => {
    await api.put(`/api/kb/${row.id}`, { enabled: !row.enabled });
    await refresh();
  };

  return (
    <div className="flex h-[calc(100vh-57px)] min-h-0">
      <aside className="flex w-[320px] shrink-0 flex-col border-r border-ink-800 bg-ink-900/40">
        <div className="space-y-3 border-b border-ink-800 px-4 py-3.5">
          <div className="flex items-center justify-between">
            <h1 className="flex items-center gap-2 text-sm font-semibold text-slate-100">
              <BookOpen size={15} className="text-brand-400" /> База знаний
            </h1>
            <button className="btn-ghost px-2 py-1" onClick={() => setCreating(true)} title="Создать статью">
              <Plus size={14} />
            </button>
          </div>
          <select value={branch} onChange={(event) => setBranch(event.target.value)} className="w-full">
            <option value="">Все ветки</option>
            {data?.branches.map((option) => (
              <option key={option.key} value={option.key}>
                {option.label}
              </option>
            ))}
          </select>
          <p className="text-[11px] text-slate-600">
            Ветки независимы: правка одной не меняет поведение остальных.
          </p>
        </div>

        <div className="min-h-0 flex-1 scroll-y">
          {loading && !data ? (
            <div className="space-y-2 p-3">
              {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-14 w-full" />)}
            </div>
          ) : (
            <ul className="divide-y divide-ink-800/70">
              {items.map((item) => (
                <li key={item.id}>
                  <button
                    onClick={() => setSelected(item.id)}
                    className={cx(
                      "w-full px-4 py-3 text-left transition",
                      selected === item.id ? "bg-brand-600/10" : "hover:bg-ink-850/60",
                    )}
                  >
                    <div className="flex items-start gap-2">
                      <p className={cx("flex-1 text-sm", item.enabled ? "text-slate-100" : "text-slate-600 line-through")}>
                        {item.title}
                      </p>
                      <span className="shrink-0 text-[10px] text-slate-600">v{item.version}</span>
                    </div>
                    <p className="mt-1 text-[11px] text-slate-500">{item.branch_label}</p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </aside>

      <section className="min-w-0 flex-1 scroll-y p-6">
        {!article ? (
          <EmptyState title="Выберите статью" />
        ) : (
          <div className="mx-auto max-w-3xl space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge>{article.branch_label}</Badge>
              <Badge>версия {article.version}</Badge>
              <Badge className={article.enabled ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300" : ""}>
                {article.enabled ? "активна" : "отключена"}
              </Badge>
              <span className="text-[11px] text-slate-600">обновлено {dateTimeOf(article.updated_at)}</span>
              <div className="ml-auto flex gap-2">
                <button className="btn-ghost" onClick={() => setShowRevisions(true)}>
                  <History size={14} /> Версии
                </button>
                <button
                  className="btn-primary"
                  onClick={() => void save()}
                  disabled={!draft}
                >
                  <Save size={14} /> Сохранить
                </button>
              </div>
            </div>

            <Card className="p-5 space-y-4">
              <Field label="Заголовок">
                <input
                  className="w-full"
                  value={draft?.title ?? article.title}
                  onChange={(event) =>
                    setDraft({ title: event.target.value, body: draft?.body ?? article.body })
                  }
                />
              </Field>
              <Field label="Содержимое" hint="Фрагменты попадают в контекст ответа AI (см. Logs → KB fragments)">
                <textarea
                  className="min-h-[320px] w-full resize-y font-mono text-[13px] leading-relaxed"
                  value={draft?.body ?? article.body}
                  onChange={(event) =>
                    setDraft({ title: draft?.title ?? article.title, body: event.target.value })
                  }
                />
              </Field>
              <Toggle
                checked={article.enabled}
                onChange={() => void toggleEnabled(article)}
                label="Использовать статью в ответах AI"
                hint="Отключённая статья мгновенно перестаёт влиять на диалоги"
              />
              {article.tags.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {article.tags.map((tag) => (
                    <Badge key={tag}>{tag}</Badge>
                  ))}
                </div>
              )}
            </Card>
          </div>
        )}
      </section>

      {showRevisions && article && (
        <RevisionsDialog
          articleId={article.id}
          onClose={() => setShowRevisions(false)}
          onRestored={() => {
            setShowRevisions(false);
            void refresh();
          }}
        />
      )}
      {creating && (
        <CreateDialog
          branches={data?.branches ?? []}
          onClose={() => setCreating(false)}
          onCreated={(id) => {
            setCreating(false);
            setSelected(id);
            void refresh();
          }}
        />
      )}
    </div>
  );
}

function RevisionsDialog({
  articleId,
  onClose,
  onRestored,
}: {
  articleId: number;
  onClose: () => void;
  onRestored: () => void;
}) {
  const { data } = usePoll<{ items: RevisionRow[] }>(
    () => api.get(`/api/kb/${articleId}/revisions`),
    0,
  );

  const restore = async (version: number) => {
    await api.post(`/api/kb/${articleId}/restore/${version}`);
    onRestored();
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-6 backdrop-blur-sm">
      <Card className="w-full max-w-2xl animate-fade-in">
        <div className="flex items-center justify-between border-b border-ink-700 px-5 py-4">
          <h3 className="text-sm font-semibold text-slate-100">История версий</h3>
          <button className="btn-ghost px-2" onClick={onClose}>
            <X size={15} />
          </button>
        </div>
        <div className="max-h-[60vh] scroll-y p-5">
          {!data?.items.length ? (
            <EmptyState title="Версий пока нет" />
          ) : (
            <ul className="space-y-2">
              {data.items.map((revision) => (
                <li key={revision.version} className="rounded-lg border border-ink-700 bg-ink-850 p-3">
                  <div className="flex items-center gap-2">
                    <Badge>v{revision.version}</Badge>
                    <span className="text-xs text-slate-200">{revision.title}</span>
                    <span className="ml-auto text-[10px] text-slate-600">
                      {dateTimeOf(revision.at)} · {revision.author}
                    </span>
                  </div>
                  <p className="mt-2 line-clamp-3 text-[11px] leading-relaxed text-slate-500">
                    {revision.body.slice(0, 260)}
                  </p>
                  <button className="btn-ghost mt-2 py-1 text-xs" onClick={() => void restore(revision.version)}>
                    <RotateCcw size={12} /> Откатить к этой версии
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>
    </div>
  );
}

function CreateDialog({
  branches,
  onClose,
  onCreated,
}: {
  branches: { key: string; label: string }[];
  onClose: () => void;
  onCreated: (id: number) => void;
}) {
  const [branch, setBranch] = useState(branches[0]?.key ?? "sales_rules");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");

  const create = async () => {
    if (!title.trim()) return;
    const slug = `custom-${Date.now()}`;
    const result = await api.post<{ id: number }>("/api/kb", {
      branch,
      slug,
      title: title.trim(),
      body,
      tags: [],
    });
    onCreated(result.id);
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-6 backdrop-blur-sm">
      <Card className="w-full max-w-xl animate-fade-in">
        <div className="flex items-center justify-between border-b border-ink-700 px-5 py-4">
          <h3 className="text-sm font-semibold text-slate-100">Новая статья БЗ</h3>
          <button className="btn-ghost px-2" onClick={onClose}>
            <X size={15} />
          </button>
        </div>
        <div className="space-y-4 p-5">
          <Field label="Ветка">
            <select className="w-full" value={branch} onChange={(event) => setBranch(event.target.value)}>
              {branches.map((option) => (
                <option key={option.key} value={option.key}>
                  {option.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Заголовок">
            <input className="w-full" value={title} onChange={(event) => setTitle(event.target.value)} />
          </Field>
          <Field label="Содержимое">
            <textarea
              className="min-h-[180px] w-full resize-y"
              value={body}
              onChange={(event) => setBody(event.target.value)}
            />
          </Field>
          <div className="flex justify-end gap-2">
            <button className="btn-ghost" onClick={onClose}>
              Отмена
            </button>
            <button className="btn-primary" onClick={() => void create()} disabled={!title.trim()}>
              Создать
            </button>
          </div>
        </div>
      </Card>
    </div>
  );
}
