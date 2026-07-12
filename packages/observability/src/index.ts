const SENSITIVE_KEY_PATTERN = /password|secret|token|authorization|cookie|api[_-]?key|private[_-]?key/i;

export interface TraceLogContext {
  request_id: string;
  trace_id: string;
  tenant_id?: string;
  biz_domain?: string;
  service: string;
}

export function redactSensitiveValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(redactSensitiveValue);
  }

  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, nested]) => [
        key,
        SENSITIVE_KEY_PATTERN.test(key) ? "[REDACTED]" : redactSensitiveValue(nested),
      ]),
    );
  }

  return value;
}
