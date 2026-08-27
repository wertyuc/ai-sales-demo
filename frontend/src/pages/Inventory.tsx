import { useMemo, useState } from "react";
import { Boxes, PackageX, Search } from "lucide-react";
import { api } from "../lib/api";
import type { Product } from "../lib/api";
import { usePoll } from "../hooks/usePoll";
import { money } from "../lib/format";
import { Badge, Card, EmptyState, Skeleton, Stat, cx } from "../components/ui";

interface InventoryResponse {
  items: Product[];
  total: number;
  in_stock: number;
  out_of_stock: number;
  categories: string[];
  types: string[];
  adapters: Record<string, string>;
}

const CONDITION_STYLE: Record<string, string> = {
  "A+": "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  A: "border-sky-500/40 bg-sky-500/10 text-sky-300",
  B: "border-slate-600 bg-slate-700/25 text-slate-300",
};

export default function Inventory() {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [type, setType] = useState("");
  const [onlyStock, setOnlyStock] = useState(false);

  const { data, loading, refresh } = usePoll<InventoryResponse>(
    () => api.get<InventoryResponse>("/api/inventory"),
    15000,
  );

  const items = useMemo(() => {
    let rows = data?.items ?? [];
    const needle = query.trim().toLowerCase();
    if (needle) {
      rows = rows.filter(
        (row) =>
          row.title.toLowerCase().includes(needle) ||
          row.sku.toLowerCase().includes(needle) ||
          row.cpu.toLowerCase().includes(needle) ||
          row.gpu.toLowerCase().includes(needle),
      );
    }
    if (category) rows = rows.filter((row) => row.category === category);
    if (type) rows = rows.filter((row) => row.type === type);
    if (onlyStock) rows = rows.filter((row) => row.stock > 0);
    return rows;
  }, [data, query, category, type, onlyStock]);

  const setStock = async (id: number, stock: number) => {
    await api.post(`/api/inventory/${id}/stock`, { stock: Math.max(0, stock) });
    await refresh();
  };

  return (
    <div className="h-full scroll-y p-6 space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-slate-100">Inventory</h1>
        <p className="mt-0.5 text-xs text-slate-500">
          Источник наличия для AI. В production подменяется на МойСклад —{" "}
          <span className="font-mono text-slate-400">{data?.adapters.inventory}</span>
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Позиций" value={data?.total ?? "—"} icon={<Boxes size={15} />} />
        <Stat label="В наличии" value={data?.in_stock ?? "—"} tone="good" />
        <Stat label="Нет в наличии" value={data?.out_of_stock ?? "—"} tone="bad" icon={<PackageX size={15} />} />
        <Stat
          label="Средняя цена"
          value={
            data?.items.length
              ? money(Math.round(data.items.reduce((sum, item) => sum + item.price, 0) / data.items.length))
              : "—"
          }
        />
      </div>

      <Card>
        <div className="flex flex-wrap items-center gap-3 border-b border-ink-700 px-5 py-3">
          <div className="relative min-w-[220px] flex-1">
            <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Модель, SKU, процессор, видеокарта…"
              className="w-full pl-9"
            />
          </div>
          <select value={type} onChange={(event) => setType(event.target.value)}>
            <option value="">Все типы</option>
            {data?.types.map((option) => (
              <option key={option} value={option}>
                {option === "laptop" ? "Ноутбуки" : "ПК"}
              </option>
            ))}
          </select>
          <select value={category} onChange={(event) => setCategory(event.target.value)}>
            <option value="">Все категории</option>
            {data?.categories.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
          <button
            onClick={() => setOnlyStock((value) => !value)}
            className={cx("btn-ghost", onlyStock && "border-brand-500/50 text-brand-200")}
          >
            Только в наличии
          </button>
          <span className="ml-auto text-[11px] text-slate-500">{items.length} позиций</span>
        </div>

        {loading && !data ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 8 }).map((_, index) => (
              <Skeleton key={index} className="h-12 w-full" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <EmptyState title="Ничего не найдено" hint="Сбросьте фильтры или измените запрос." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[980px] text-sm">
              <thead>
                <tr className="border-b border-ink-800 text-left text-[11px] uppercase tracking-wide text-slate-500">
                  <th className="px-5 py-2.5 font-medium">Модель</th>
                  <th className="px-3 py-2.5 font-medium">Конфигурация</th>
                  <th className="px-3 py-2.5 font-medium">Сост.</th>
                  <th className="px-3 py-2.5 font-medium text-right">Цена</th>
                  <th className="px-3 py-2.5 font-medium text-right">Объявление</th>
                  <th className="px-3 py-2.5 font-medium">Пригодность</th>
                  <th className="px-5 py-2.5 font-medium text-center">Остаток</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-800/70">
                {items.map((item) => (
                  <tr key={item.id} className={cx("hover:bg-ink-850/40", item.stock === 0 && "opacity-60")}>
                    <td className="px-5 py-2.5">
                      <p className="font-medium text-slate-100">{item.title}</p>
                      <p className="text-[11px] text-slate-500">
                        {item.sku} · {item.category}
                      </p>
                    </td>
                    <td className="px-3 py-2.5 text-[11px] text-slate-400">
                      <p>{item.cpu}</p>
                      <p>
                        {item.gpu} · {item.ram} ГБ · {item.storage}
                      </p>
                    </td>
                    <td className="px-3 py-2.5">
                      <Badge className={CONDITION_STYLE[item.condition] ?? ""}>{item.condition}</Badge>
                    </td>
                    <td className="px-3 py-2.5 text-right font-medium text-slate-100 tabular-nums">
                      от {money(item.price)}
                    </td>
                    <td className="px-3 py-2.5 text-right text-[11px] text-slate-500 tabular-nums">
                      {money(item.listing_price)}
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex gap-1">
                        {(["games", "work", "creative"] as const).map((task) => (
                          <div key={task} className="w-9" title={`${task}: ${item.suitability[task] ?? 0}`}>
                            <div className="h-1 rounded-full bg-ink-700">
                              <div
                                className={cx(
                                  "h-full rounded-full",
                                  (item.suitability[task] ?? 0) >= 60 ? "bg-emerald-500" : "bg-slate-500",
                                )}
                                style={{ width: `${item.suitability[task] ?? 0}%` }}
                              />
                            </div>
                            <p className="mt-0.5 text-[9px] text-slate-600">{task.slice(0, 4)}</p>
                          </div>
                        ))}
                      </div>
                    </td>
                    <td className="px-5 py-2.5">
                      <div className="flex items-center justify-center gap-1.5">
                        <button
                          className="h-6 w-6 rounded border border-ink-600 text-slate-400 hover:bg-ink-700"
                          onClick={() => void setStock(item.id, item.stock - 1)}
                        >
                          −
                        </button>
                        <span
                          className={cx(
                            "w-8 text-center text-sm font-semibold tabular-nums",
                            item.stock === 0 ? "text-rose-400" : "text-slate-100",
                          )}
                        >
                          {item.stock}
                        </span>
                        <button
                          className="h-6 w-6 rounded border border-ink-600 text-slate-400 hover:bg-ink-700"
                          onClick={() => void setStock(item.id, item.stock + 1)}
                        >
                          +
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <p className="text-[11px] text-slate-600">
        Поставьте остаток 0 у модели и спросите про неё в Live Sales — AI откажется подтверждать
        наличие и предложит альтернативы.
      </p>
    </div>
  );
}
