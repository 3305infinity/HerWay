/** Shared shapes for data returned by the HerWay backend. */

export type ResourceVerification =
  | 'official_source'
  | 'likely_official'
  | 'unverified_listing';

export interface MatchedResource {
  id: string;
  name: string;
  category: string;
  phone?: string | null;
  address?: string | null;
  url?: string | null;
  operating_hours?: string | null;
  rating?: number | null;
  verification: ResourceVerification;
  verification_note?: string;
  notes?: string | null;
  source_domain?: string | null;
  retrieved_at?: string;
}

export interface EvidenceItem {
  id: string;
  source_title: string;
  url?: string | null;
  domain?: string | null;
  source_type?: string;
  relevance?: number;
  freshness?: number;
  authority?: number;
  claim_supported?: string;
  extracted_facts?: string[];
  contradictions?: Array<{
    claim: string;
    source_a: string;
    source_b: string;
    difference: string;
    resolution_status: string;
  }>;
  confidence?: 'high' | 'medium' | 'low';
  confidence_score?: number;
  status?:
    | 'verified_strongly_supported'
    | 'partially_supported'
    | 'conflicting'
    | 'unverified';
  why_this_source_matters?: string;
}

export interface SafetyActionItem {
  id: string;
  title: string;
  description: string;
  phase: string;
  priority: string;
  status: string;
  evidence_ids?: string[];
  resource_ids?: string[];
  safety_caveat?: string | null;
  supporting_url?: string | null;
  completed_at?: string | null;
}

export interface ActionItem {
  id: string;
  title: string;
  description: string;
  action_type?: string;
  priority?: string;
  timing_phase?: string;
  evidence_ids?: string[];
  status?: string;
  completed?: boolean;
  supporting_url?: string | null;
}

export interface SafetyAssessment {
  immediate_safety_concern: boolean;
  threats_present: boolean;
  repeated_harassment: boolean;
  digital_safety_concern: boolean;
  support_available: boolean;
  safe_place_available: boolean;
  financial_dependence: boolean;
  workplace_harassment: boolean;
  presence_of_dependents: boolean;
  escalating_behavior: boolean;
  information_missing: boolean;
  indicator_justifications?: Record<string, string>;
  context_summary: string;
  critical_safety_notes?: string[];
  missing_safety_information?: string[];
  [key: string]: unknown;
}

export interface SafetyPlanUpdate {
  update_id: string;
  timestamp: string;
  why_plan_changed: string;
  what_changed?: string[];
  new_recommended_steps?: string[];
}

export interface SafetyPlan {
  case_id: string;
  category: string;
  assessment: SafetyAssessment;
  right_now_actions: SafetyActionItem[];
  next_24h_actions: SafetyActionItem[];
  document_safe_actions: SafetyActionItem[];
  support_network_actions: SafetyActionItem[];
  formal_options_actions: SafetyActionItem[];
  ongoing_actions: SafetyActionItem[];
  actions: SafetyActionItem[];
  matched_resources: MatchedResource[];
  things_to_avoid?: string[];
  updates_history?: SafetyPlanUpdate[];
  disclaimer?: string;
  updated_at?: string;
}

export interface ActionPlan {
  case_id: string;
  summary?: string;
  disclaimer?: string;
  immediate_actions?: ActionItem[];
  next_actions?: ActionItem[];
  escalation_options?: ActionItem[];
  actions?: ActionItem[];
  documents_or_evidence_to_collect?: string[];
  things_to_avoid?: string[];
  unresolved_questions?: string[];
}

export interface ResearchTraceEntry {
  task_id: string;
  why_searched: string;
  query: string;
  engine: string;
  results_found: number;
  sources_used?: number;
  selected_urls?: string[];
  time_taken_ms: number;
  is_cached?: boolean;
  freshness_policy?: string;
  success: boolean;
  error?: string | null;
}

export interface ResearchDegradation {
  stage: string;
  reason: string;
  user_message: string;
}

export interface Situation {
  case_summary: string;
  category: string;
  urgency?: string;
  location?: string | null;
  user_goal?: string;
  known_facts?: string[];
  user_claims?: string[];
  unknowns?: string[];
  missing_information?: string[];
  questions_to_ask?: string[];
}

export interface LocalResource {
  id?: string;
  name: string;
  type?: string;
  address?: string | null;
  phone?: string | null;
  rating?: number | null;
  hours?: string | null;
  website?: string | null;
  source_domain?: string | null;
  retrieved_at?: string;
  verification: ResourceVerification;
  verification_note?: string;
  relevance_reason?: string;
}

export interface CaseRecord {
  id: string;
  user_id?: string;
  title: string;
  category: string;
  situation_text: string;
  status: string;
  created_at: string;
  updated_at: string;
  situation?: Situation | null;
  location_context?: string | null;
  evidence?: EvidenceItem[];
  action_plan?: ActionPlan | null;
  safety_plan?: SafetyPlan | null;
  local_resources?: LocalResource[];
  research_trace?: ResearchTraceEntry[];
  research_degradations?: ResearchDegradation[];
  research_location_used?: string | null;
  conversation?: Array<{ role: string; content: string }>;
}

export interface ChatReply {
  reply: string;
  sources?: string[];
  searched_query?: string | null;
  tool_used?: string | null;
  plan_adapted?: boolean;
  safety_plan?: SafetyPlan | null;
  community_posts?: Array<Record<string, unknown>>;
  lawbot_docs?: string[];
  formal_report?: string | null;
  degraded_notice?: string | null;
}

export interface NationalHelpline {
  id: string;
  name: string;
  number: string;
  purpose: string;
  official_source_url: string;
  operating_hours: string;
  resource_category: string;
  notes?: string | null;
}

export interface OfficialPortal {
  id: string;
  name: string;
  url: string;
  purpose: string;
  resource_category: string;
}

export interface NationalResources {
  helplines: NationalHelpline[];
  portals: OfficialPortal[];
  note: string;
}
