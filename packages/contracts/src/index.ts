export type RequestSource = "BUSINESS_SERVICE" | "AGENT_TOOL" | "ADMIN" | "INTERNAL";

export interface TenantBizContext {
  tenant_id: string;
  biz_domain: string;
  user_id?: string;
  roles?: readonly string[];
  request_id: string;
  trace_id: string;
  request_source: RequestSource;
}

export interface ResourceScope {
  resource_type: string;
  resource_id?: string;
  owner_user_id?: string;
  attributes?: Readonly<Record<string, unknown>>;
}

export interface ApiErrorPayload {
  code: string;
  message: string;
  details?: Readonly<Record<string, unknown>>;
}

export interface UnifiedApiResponse<T> {
  success: boolean;
  request_id: string;
  trace_id: string;
  data?: T;
  error?: ApiErrorPayload;
}

export interface AuditEventEnvelope {
  event_id: string;
  event_type: string;
  tenant_id: string;
  biz_domain: string;
  request_id: string;
  trace_id: string;
  actor_id?: string;
  resource?: ResourceScope;
  decision: "ALLOW" | "DENY" | "ERROR";
  occurred_at: string;
  payload?: Readonly<Record<string, unknown>>;
}
