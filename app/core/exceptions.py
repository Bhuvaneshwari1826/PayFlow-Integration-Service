class TakaadaBaseException(Exception):
    """Base exception for all application errors."""
    pass


class ExternalAPIException(TakaadaBaseException):
    """Raised when the external accounting API returns an error."""
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"External API error {status_code}: {detail}")


class ExternalAPITimeoutException(TakaadaBaseException):
    """Raised when the external accounting API times out."""
    pass


class ExternalAPIRateLimitException(ExternalAPIException):
    """Raised when we hit the external API rate limit (429)."""
    pass


class ResourceNotFoundException(TakaadaBaseException):
    """Raised when a requested resource does not exist locally."""
    def __init__(self, resource: str, identifier: str):
        self.resource = resource
        self.identifier = identifier
        super().__init__(f"{resource} not found: {identifier}")


class SyncException(TakaadaBaseException):
    """Raised when a sync operation fails."""
    pass
