export interface User {
  id: number;
  email: string;
  name: string;
  role: string;
  role_label: string;
  role_description: string;
  permissions: string[];
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface Source {
  id: number;
  name: string;
  site_type: string;
  site_type_label: string;
  enabled: boolean;
  last_sync_at: string | null;
  raw_count: number;
  sync_status: string;
  note: string;
}

export interface ParsePreview {
  version: string;
  status: string;
  salary_min: number | null;
  salary_max: number | null;
  salary_median: number | null;
  annual_months: number;
  unit_kind: string;
  confidence: number;
  reason_code: string;
  flags: string[];
  matched_rules: string[];
  canonical_title: string;
  function_type: string;
  seniority: string;
  title_confidence: number;
  matched_terms: string[];
  city: string;
}

export interface RawPosting {
  id: number;
  source_id: number;
  source_name: string;
  external_id: string;
  title_raw: string;
  salary_raw: string;
  city_raw: string;
  experience_raw: string;
  employment_type_raw: string;
  company: string;
  status: string;
  status_label: string;
  parse_reason: string;
  rule_version: string;
  published_at: string | null;
  posting_id: number | null;
}

export interface RawDetail extends RawPosting {
  raw_json: Record<string, unknown>;
  current: ParsePreview | null;
  compare_versions: ParsePreview[];
}

export interface Posting {
  id: number;
  raw_id: number;
  source_id: number;
  source_name: string;
  canonical_title: string;
  function_type: string;
  function_label: string;
  seniority: string;
  seniority_label: string;
  city: string;
  salary_min: number | null;
  salary_max: number | null;
  salary_median: number | null;
  salary_unit: string;
  annual_months: number;
  is_fulltime: boolean;
  confidence: number;
  rule_version: string;
  title_matches: string[];
  quality_flags: string[];
  quality_flag_labels: string[];
  quality_status: string;
  is_corrected: boolean;
  parse_reason: string;
  raw_title: string;
  raw_salary: string;
}

export interface Paged<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
  pages: number;
}

export interface PostingStats {
  total: number;
  flagged: number;
  corrected: number;
  by_city: { key: string; count: number }[];
  by_function: { key: string; count: number }[];
  by_seniority: { key: string; count: number }[];
}

export interface ParseRule {
  id: number;
  code: string;
  rule_set: string;
  version: string;
  rule_type: string;
  name: string;
  pattern: string;
  action: string;
  description: string;
  hit_count: number;
  enabled: boolean;
  is_active_set: boolean;
}

export interface TrialResult {
  version: string;
  attempts: number;
  hits: number;
  misses: number;
  hit_rate: number;
  hit_rate_pct: number;
  reason_breakdown: Record<string, number>;
  rule_hits: Record<string, number>;
  samples: { raw: string; status: string; salary_min: number | null; salary_max: number | null; annual_months: number; reason_code: string }[];
}

export interface ReparseResult {
  previous_version: string;
  active_version: string;
  before: TrialResult;
  after: TrialResult;
  updated_raws: number;
  updated_postings: number;
  skipped_corrected: number;
  duration_ms: number;
}

export interface Benchmark {
  id: number;
  city: string;
  function_type: string;
  function_label: string;
  sample_count: number;
  p25: number;
  p50: number;
  p75: number;
  rule_version: string;
  version: number;
  published: boolean;
  review_status: string;
  superseded_by_version: string;
  upgrade_id: number | null;
  generated_at: string | null;
}

export interface BenchmarkReport extends Benchmark {
  distribution: { low: number; high: number; count: number }[];
  seniority_breakdown: { seniority: string; label: string; sample_count: number; p50: number }[];
}

export interface AffectedPosting {
  posting_id: number;
  raw_id: number;
  title: string;
  raw_title: string;
  salary_raw: string;
  city: string;
  salary_min: number | null;
  salary_max: number | null;
  salary_median: number | null;
  rule_version: string;
  quality_flags: string[];
  raw_status: string;
  is_corrected: boolean;
  changed: boolean;
  kept_corrected: boolean;
  after: {
    title: string;
    city: string;
    salary_min: number | null;
    salary_max: number | null;
    salary_median: number | null;
    quality_flags: string[];
    raw_status: string;
    rule_version: string;
  } | null;
}

export interface UpgradePreview {
  target_version: string;
  active_version: string;
  already_applied: boolean;
  existing_batch: UpgradeBatch | null;
  affected_totals: { postings: number; changed: number; kept_corrected: number };
  affected_postings: AffectedPosting[];
  reports_to_mark: Benchmark[];
  published_reports: Benchmark[];
  reports_to_generate: { city: string; function_type: string; function_label: string }[];
  target_existing_reports: Benchmark[];
}

export interface UpgradeBatch {
  id: number;
  target_version: string;
  previous_version: string;
  status: string;
  before_rate: TrialResult | null;
  after_rate: TrialResult | null;
  affected_snapshot: Record<string, unknown> | null;
  updated_raws: number;
  updated_postings: number;
  skipped_corrected: number;
  benchmarks_marked: number;
  reports_created: number;
  reports_skipped: number;
  actor_email: string;
  duration_ms: number;
  summary: string;
  started_at: string | null;
  finished_at: string | null;
  idempotent: boolean;
}

export interface QualityItem {
  posting: Posting;
  primary_flag: string;
  flag_labels: string[];
}

export interface QualityPage extends Paged<QualityItem> {
  by_type: { flag: string; label: string; count: number }[];
}
