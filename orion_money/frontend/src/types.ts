/**
 * Type mirrors of the ORION FastAPI response shapes (orion/api.py).
 *
 * Rule from the backend: every money value is an INTEGER amount in paise and
 * ALSO carries a formatted `₹` string (orion.ledger.fmt_paise). Consumers
 * should display the *_formatted strings and never re-derive currency.
 */

export type AutonomyLevel = 'ENABLED' | 'APPROVAL' | 'BLOCKED';

export interface StatusResponse {
  mode: string;
  kill_switch_active: boolean;
  kill_switch_reason: string | null;
  model_status: string;
  model_detail: string;
  db_ok: boolean;
  uptime_s: number;
  autonomy: Record<string, AutonomyLevel>;
}

export interface HealthResponse {
  ok: boolean;
  checks: Record<string, string>;
}

export interface LedgerSummary {
  currency: string;
  capital: number;
  capital_formatted: string;
  available_cash: number;
  available_cash_formatted: string;
  reserved_cash: number;
  reserved_cash_formatted: string;
  spent: number;
  spent_formatted: string;
  revenue: number;
  revenue_formatted: string;
  verified_revenue: number;
  verified_revenue_formatted: string;
  pending_revenue: number;
  pending_revenue_formatted: string;
  total_revenue: number;
  total_revenue_formatted: string;
  fees: number;
  fees_formatted: string;
  refunds: number;
  refunds_formatted: string;
  net_profit: number;
  net_profit_formatted: string;
  revenue_statuses: Record<string, number>;
  entry_count: number;
  target_paise: number;
  target_paise_formatted: string;
}

export interface LedgerEntry {
  id: number;
  type: string;
  amount_paise: number;
  amount_formatted: string;
  currency: string;
  source: string;
  destination: string;
  reference: string | null;
  status: string;
  verification_method: string | null;
  confidence: number | null;
  correlation_id: string | null;
  created_at: string;
  metadata: Record<string, unknown>;
}

export interface LedgerResponse {
  summary: LedgerSummary;
  entries: LedgerEntry[];
}

export interface SpendResult {
  status: 'SIMULATED' | 'PENDING' | 'COMPLETED';
  simulated?: boolean;
  mode: string;
  approval: Approval | null;
  entry: LedgerEntry | null;
}

export interface RevenueResult {
  entry: LedgerEntry;
  status: string;
  verified: boolean;
  verified_revenue_paise: number;
  verified_revenue_formatted: string;
  available_cash_paise: number;
  available_cash_formatted: string;
}

export interface Approval {
  id: number;
  kind: string;
  why: string;
  payload: Record<string, unknown>;
  cost_paise: number | null;
  cost_formatted: string | null;
  potential_revenue_paise: number | null;
  risk_level: string | null;
  destination: string;
  correlation_id: string | null;
  status: string;
  decision: string | null;
  decision_reason: string | null;
  created_at: string;
  decided_at: string | null;
  expires_at: string | null;
}

export interface ApprovalsResponse {
  approvals: Approval[];
  count: number;
}

export interface ApprovalDecisionResult {
  status: string;
  approval: Approval;
  entry: LedgerEntry | null;
}

export interface Opportunity {
  id: number;
  name: string;
  kind: string;
  status: string;
  source: string;
  source_connector: string;
  url: string;
  description: string;
  estimated_value_paise: number;
  estimated_value_formatted: string;
  cost_paise: number;
  cost_formatted: string;
  score_0_100: number | null;
  factors: Record<string, unknown>;
  suspicious: boolean;
  suspicious_reason: string | null;
  rejected_reason: string | null;
  last_seen: string;
  created_at: string;
}

export interface OpportunitiesResponse {
  opportunities: Opportunity[];
  count: number;
}

export interface ScanResult {
  created: number;
  scored: number;
  total: number;
}

export interface StrategyPerformance {
  strategy_id: number;
  run_count: number;
  total_profit_paise: number;
  total_profit_paise_formatted: string;
  total_revenue_paise: number;
  total_revenue_paise_formatted: string;
  total_fees_paise: number;
  total_fees_paise_formatted: string;
  total_time_hours: number;
  avg_profit_per_hour_paise: number;
  avg_profit_per_hour_paise_formatted: string;
  win_rate: number;
  wins: number;
  losses: number;
}

export interface Strategy {
  id: number;
  name: string;
  status: string;
  created_at: string;
  description: string;
  risk_level: string | null;
  automation_level: string | null;
  min_opportunity_score: number | null;
  max_spend_paise: number;
  max_spend_formatted: string;
  required_capital_paise: number;
  required_capital_formatted: string;
  required_skills: string[];
  allowed_risk_levels: string[];
  activation_reasons: string[];
  performance_summary: StrategyPerformance;
}

export interface StrategiesResponse {
  strategies: Strategy[];
  count: number;
}

export interface Experiment {
  id: number;
  name: string;
  status: string;
  created_at: string;
  hypothesis: string | null;
  strategy_id: number | null;
  params_paise: number | null;
  params_formatted: string | null;
  expected_result: string | null;
  evaluation: unknown;
}

export interface ExperimentsResponse {
  experiments: Experiment[];
  count: number;
}

export interface ActivityEvent {
  event: string;
  timestamp: string;
  agent: string;
  entity_id: unknown;
  metadata: Record<string, unknown>;
  correlation_id: string | null;
}

export interface ActivityRecentResponse {
  events: ActivityEvent[];
  count: number;
}

export interface KillSwitchResult {
  active: boolean;
  reason: string;
}

export interface ApiErrorBody {
  error?: string;
  detail?: string | unknown[];
  reasons?: string[];
}