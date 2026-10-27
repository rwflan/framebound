"""Stable service error codes. Transports must not turn failure into empty success."""


class ServiceError(Exception):
    code: str = "error"
    retryable: bool = False
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidInput(ServiceError):
    code = "invalid_input"


class StaleRevision(ServiceError):
    code = "stale_revision"


class Unsupported(ServiceError):
    code = "unsupported"
    def __init__(self, message: str, capability: str = ""):
        super().__init__(message)
        self.capability = capability


class RateLimited(ServiceError):
    code = "rate_limited"
    retryable = True


class ProviderTimeout(ServiceError):
    code = "provider_timeout"
    retryable = True


class Cancelled(ServiceError):
    code = "cancelled"


class AuthorizationError(ServiceError):
    code = "forbidden"
