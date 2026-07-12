export class AppError extends Error {
  public constructor(
    public readonly code: string,
    message: string,
    public readonly statusCode: number,
    public readonly details?: Readonly<Record<string, unknown>>,
  ) {
    super(message);
    this.name = new.target.name;
  }
}

export class ValidationError extends AppError {
  public constructor(message: string, details?: Readonly<Record<string, unknown>>) {
    super("VALIDATION_ERROR", message, 400, details);
  }
}

export class UnauthorizedError extends AppError {
  public constructor(message = "Authentication is required") {
    super("UNAUTHORIZED", message, 401);
  }
}

export class ForbiddenError extends AppError {
  public constructor(message = "The operation is not allowed", details?: Readonly<Record<string, unknown>>) {
    super("FORBIDDEN", message, 403, details);
  }
}

export class NotFoundError extends AppError {
  public constructor(message = "The requested resource was not found") {
    super("NOT_FOUND", message, 404);
  }
}

export class ConflictError extends AppError {
  public constructor(message: string, details?: Readonly<Record<string, unknown>>) {
    super("CONFLICT", message, 409, details);
  }
}

export class DependencyUnavailableError extends AppError {
  public constructor(message: string, details?: Readonly<Record<string, unknown>>) {
    super("DEPENDENCY_UNAVAILABLE", message, 503, details);
  }
}
