// Thin client for the dashboard's read-only metrics API.
//
// The API is guarded by a bearer key (see app/auth.verify_dashboard_api_key).
// In development, set it via localStorage: `localStorage.dashboardKey = "..."`.

const KEY = (): string =>
  (typeof localStorage !== "undefined" && localStorage.getItem("dashboardKey")) || "";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { Authorization: `Bearer ${KEY()}` },
  });
  if (!res.ok) throw new Error(`${path} failed: ${res.status}`);
  return res.json() as Promise<T>;
}

export interface Summary {
  group_slug: string | null;
  requests: number;
  scored: number;
  reviewed: number;
  skipped: number;
  failed: number;
  coverage_pct: number;
  skipped_by_reason: Record<string, number>;
  median_risk: number | null;
  median_complexity: number | null;
  median_time_to_review_seconds: number | null;
  estimated_cost_usd: number;
  time_saved_hours: number;
  tokens: Record<string, number>;
  feedback: { up: number; down: number };
}

export interface Histograms {
  risk: number[];
  complexity: number[];
}

export interface DayPoint {
  date: string;
  requests: number;
  reviewed: number;
  skipped: number;
  cost_usd: number;
}

export interface Revision {
  id: number;
  revision_id: number;
  status: string;
  risk: number | null;
  complexity: number | null;
  skipped_reason: string | null;
  group: string | null;
  estimated_cost_usd: number;
}

export interface Group {
  slug: string;
  enabled: boolean;
  risk_threshold: number;
  complexity_threshold: number;
  restrict_to_member_authors: boolean;
  has_skill: boolean;
}

const qs = (group?: string) => (group ? `?group=${encodeURIComponent(group)}` : "");

export const fetchSummary = (group?: string) => get<Summary>(`/summary${qs(group)}`);
export const fetchHistograms = (group?: string) =>
  get<Histograms>(`/histograms${qs(group)}`);
export const fetchTimeseries = (group?: string) =>
  get<DayPoint[]>(`/timeseries${qs(group)}`);
export const fetchRevisions = (group?: string) =>
  get<{ total: number; items: Revision[] }>(`/revisions${qs(group)}`);
export const fetchGroups = () => get<Group[]>(`/groups`);
