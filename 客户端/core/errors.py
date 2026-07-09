class ClientError(Exception):
    """Base exception for client errors."""
    pass


class ConfigError(ClientError):
    """Configuration loading or validation error."""
    pass


class APIError(ClientError):
    """API request failed."""
    pass
