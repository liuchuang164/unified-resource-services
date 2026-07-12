import { ForbiddenError } from "@urs/common-errors";

export interface CapabilityTokenClaims {
  jti: string;
  issuer: string;
  audience: string;
  subject: string;
  tenant_id: string;
  biz_domain: string;
  tool_name?: string;
  actions?: readonly string[];
  resource_scope?: Readonly<Record<string, unknown>>;
  issued_at: number;
  expires_at: number;
}

export interface ExpectedCapabilityScope {
  tenant_id: string;
  biz_domain: string;
  tool_name?: string;
  action?: string;
}

export interface CapabilityTokenVerifier {
  verifyAndDecode(token: string): Promise<CapabilityTokenClaims>;
}

export function assertCapabilityScope(
  claims: CapabilityTokenClaims,
  expected: ExpectedCapabilityScope,
): void {
  if (claims.tenant_id !== expected.tenant_id || claims.biz_domain !== expected.biz_domain) {
    throw new ForbiddenError("Capability token tenant or business scope does not match");
  }

  if (expected.tool_name !== undefined && claims.tool_name !== expected.tool_name) {
    throw new ForbiddenError("Capability token does not allow the requested tool");
  }

  if (expected.action !== undefined && !(claims.actions ?? []).includes(expected.action)) {
    throw new ForbiddenError("Capability token does not allow the requested action");
  }
}
