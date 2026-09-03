export interface DatasetInfo {
  id: string;
  label: string;
  orders: number;
  payments: number;
  settlements: number;
  has_ground_truth: boolean;
  created_at?: string | null;
  meta?: Record<string, unknown>;
}

export interface RunSummary {
  run_id: string;
  status: string;
  label: string | null;
  records_total: number;
  matched: number;
  exceptions: number;
  auto_resolved: number;
  ai_resolved: number;
  human_review: number;
  match_rate: number;
  duration_seconds: number;
  throughput_per_second: number;
  ai_calls: number;
  ai_coverage: number;
  created_at: string | null;
  completed_at: string | null;
  error: string | null;
}

export interface RunDetail extends RunSummary {
  manifest: {
    counts?: Record<string, number>;
    summary?: Record<string, number>;
    timings?: Record<string, number>;
    cascade?: Record<string, CascadeStage[]>;
    ai?: Record<string, number | string>;
    duplicates?: number;
    ai_candidate_pairs?: number;
    [k: string]: unknown;
  };
}

export interface CascadeStage {
  stage: string;
  rule: string;
  matched: number;
  candidates: number;
}

export interface BreakdownBucket {
  exception_type: string;
  resolution: string;
  count: number;
  impact_minor: number;
}

export interface Breakdown {
  run_id: string;
  totals: {
    gross_order_minor: number;
    gross_payment_minor: number;
    gross_settlement_minor: number;
    settlement_gap_minor: number;
  };
  buckets: BreakdownBucket[];
  generated_at: string;
}

export interface ExceptionRow {
  case_id: string;
  exception_type: string;
  resolution: string;
  merchant_id: string | null;
  currency: string | null;
  order_id: string | null;
  order_amount_minor: number | null;
  payment_amount_minor: number | null;
  settlement_amount_minor: number | null;
  expected_fee_minor: number | null;
  payment_delta_minor: number | null;
  settlement_delta_minor: number | null;
  confidence: number | null;
  ai_classification: string | null;
  ai_confidence: number | null;
  ai_explanation: string | null;
  ai_evidence: string[];
  suggested_action: string | null;
  validation_reason: string | null;
  ai_eligible: boolean;
}

export interface ExceptionPage {
  items: ExceptionRow[];
  total: number;
  offset: number;
  limit: number;
}

export interface ChatResponse {
  answer: string;
  breakdown: { label: string; amount_minor: number; count: number }[];
  followups: string[];
  used_figures: string[];
  degraded: boolean;
}

export interface BenchmarkRow {
  dataset_size: number;
  records_total: number;
  duration_seconds: number;
  throughput_per_second: number;
  matched: number;
  exceptions: number;
  match_rate: number;
  auto_resolved: number;
  ai_calls: number;
  ai_coverage: number;
  precision: number;
  recall: number;
  f1: number;
  label_accuracy: number;
}

export interface BenchmarkResponse {
  results: BenchmarkRow[];
  generated_at: string;
}

export interface EngineConfig {
  app: string;
  env: string;
  engine: Record<string, number>;
  ai: {
    enabled: boolean;
    configured: boolean;
    provider: string;
    provider_setting: string;
    model: string;
    effort: string;
    batch_size: number;
    max_concurrency: number;
    max_exceptions_per_run: number;
    usage: Record<string, number>;
  };
  cache: { backend: string; local_entries: number };
}
