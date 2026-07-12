import type { TenantBizContext } from "@urs/contracts";

export const TENANT_CANARIES = Object.freeze({
  tenantALegal: "ALPHA_LEGAL_CANARY_7F31",
  tenantARobotDog: "ALPHA_ROBOT_CANARY_9D82",
  tenantBLegal: "BETA_LEGAL_CANARY_4A66",
});

export function buildTenantBizContext(
  overrides: Partial<TenantBizContext> = {},
): TenantBizContext {
  return {
    tenant_id: "tenant_A",
    biz_domain: "LEGAL",
    user_id: "user_001",
    roles: ["TEST_USER"],
    request_id: "req_test_001",
    trace_id: "trace_test_001",
    request_source: "INTERNAL",
    ...overrides,
  };
}
