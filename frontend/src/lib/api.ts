export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T,>(path: string) => request<T>(path),
  post: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  put: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: body ? JSON.stringify(body) : undefined }),
  del: <T,>(path: string) => request<T>(path, { method: "DELETE" }),
};

// --- shared shapes ----------------------------------------------------------

export type Temperature = "COLD" | "WARM" | "HOT" | "CRITICAL";

export interface ClockState {
  now: string;
  speed: number;
  allowed_speeds: number[];
}

export interface ProviderInfo {
  provider: string;
  model: string;
  mode: string;
  configured: boolean;
  note: string;
}

export interface ConversationSummary {
  id: number;
  customer: {
    id: number;
    name: string;
    avito_id: string;
    source: string;
    color: string;
    phone: string;
  };
  mode: "ai" | "human";
  status: string;
  scenario: string;
  score: number;
  closed_count: number;
  temperature: Temperature;
  stage: string;
  stage_label: string;
  handoff_required: boolean;
  handoff_reason: string;
  handoff_kind: string;
  manager: string | null;
  last_message: string;
  last_message_role: string;
  last_message_at: string | null;
  unread_outbound: number;
  ai_silent_until: string | null;
  message_count: number;
}

export interface ChatMessage {
  id: number;
  role: "customer" | "ai" | "manager" | "system";
  text: string;
  author: string;
  kind: string;
  created_at: string;
  read_at: string | null;
  meta: Record<string, unknown>;
}

export interface QualField {
  key: string;
  label: string;
  value: string;
  closed: boolean;
  weight: number;
}

export interface Intelligence {
  available: boolean;
  lead_id?: number;
  fields: QualField[];
  score: number;
  closed_count: number;
  total_fields: number;
  qualified: boolean;
  threshold: number;
  temperature: Temperature;
  sentiment: string;
  stage: string;
  stage_label: string;
  direction: string;
  direction_label: string;
  contact_phone: string;
  products: { id: number; sku: string; title: string; price: number; condition: string; stock: number }[];
  next_action: string;
  handoff: {
    required: boolean;
    reason: string;
    kind: string;
    at: string | null;
    manager: string | null;
  };
  hot_signals: string[];
  meeting: { at: string; label: string; status: string; address: string } | null;
  task: {
    title: string;
    deadline: string;
    status: string;
    seconds_left: number;
    manager: string | null;
  } | null;
  quality: string;
  quality_label: string;
}

export interface LeadCard {
  id: number;
  conversation_id: number;
  customer: { name: string; avito_id: string; phone: string; source: string; color: string };
  stage: string;
  stage_label: string;
  direction: string;
  direction_label: string;
  temperature: Temperature;
  score: number;
  closed_count: number;
  qualification: Record<string, string>;
  budget: string;
  location: string;
  needs: string;
  timeframe: string;
  recipient: string;
  products: { id: number; sku: string; title: string; price: number }[];
  manager: string | null;
  manager_color: string | null;
  next_action: string;
  handoff_required: boolean;
  handoff_reason: string;
  notes: string;
  quality: string;
  quality_label: string;
  contact_acquired: boolean;
  meeting_scheduled: boolean;
  arrived: boolean;
  sold: boolean;
  meeting: { at: string; status: string } | null;
  task: { title: string; deadline: string; status: string } | null;
  created_at: string;
  updated_at: string;
  history?: { at: string; actor: string; field: string; old: string; new: string }[];
}

export interface Product {
  id: number;
  sku: string;
  type: string;
  brand: string;
  model: string;
  title: string;
  category: string;
  cpu: string;
  gpu: string;
  ram: number;
  storage: string;
  screen: string;
  condition: string;
  price: number;
  listing_price: number;
  stock: number;
  description: string;
  tags: string[];
  suitability: Record<string, number>;
  gpu_score: number;
  cpu_score: number;
  portability: number;
}

export interface FollowUpRow {
  id: number;
  conversation_id: number;
  customer: string;
  customer_color: string;
  kind: string;
  attempt: number;
  rule: string;
  note: string;
  status: string;
  due_at: string;
  sent_at: string | null;
  seconds_left: number;
  unread: boolean;
}

export interface TurnLogRow {
  id: number;
  conversation_id: number;
  customer: string;
  created_at: string;
  customer_message: string;
  ai_response: string;
  extracted: Record<string, unknown>;
  rules_triggered: string[];
  kb_fragments: { branch_label: string; title: string; version: number; excerpt: string }[];
  products_queried: Record<string, unknown>[];
  inventory_snapshot: { sku: string; title: string; stock: number; price: number }[];
  price_validation: Record<string, unknown>;
  safety_checks: { code: string; label: string; status: string; detail: string }[];
  crm_mutations: { field: string; from: unknown; to: unknown }[];
  handoff_reason: string;
  provider: string;
  model: string;
  latency_ms: number;
  guard_verdict: string;
  error: string;
}

export interface Analytics {
  period_days: number;
  generated_at: string;
  totals: Record<string, number>;
  rates: Record<string, number>;
  response: { avg_seconds: number; measured: number; under_2min: number };
  funnel: { key: string; label: string; value: number }[];
  quality: { key: string; label: string; value: number }[];
  temperature: { key: string; value: number }[];
  stages: { key: string; value: number }[];
  directions: { key: string; value: number }[];
  sources: { source: string; leads: number; qualified: number; rate: number }[];
  timeline: { date: string; leads: number; qualified: number; handoffs: number; meetings: number; sales: number }[];
  handoff_reasons: { code: string; label: string; value: number }[];
  top_products: { title: string; sku: string; value: number; price: number }[];
}

export interface Insights {
  generated_at: string;
  dataset: { label: string; leads: number; turns: number; note: string };
  findings: {
    id: string;
    severity: "high" | "medium" | "low";
    title: string;
    detail: string;
    recommendation: string;
    sample: number;
    confidence: string;
  }[];
  recommendations: { id: string; text: string; status: string; based_on: string }[];
}

export interface ScenarioInfo {
  key: string;
  title: string;
  description: string;
  customer: string;
  expect: string;
  steps: number;
}

export interface ManagerRow {
  id: number;
  name: string;
  role: string;
  on_shift: boolean;
  color: string;
  assigned_total: number;
  open_tasks: number;
  leads: number;
  last_assigned_at: string | null;
}

export interface KBArticleRow {
  id: number;
  branch: string;
  branch_label: string;
  slug: string;
  title: string;
  body: string;
  enabled: boolean;
  version: number;
  tags: string[];
  updated_at: string;
}
