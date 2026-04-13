class MakerError(Exception):
    """Base application error."""


class ConfigurationError(MakerError):
    """Raised when local configuration is incomplete."""


class NotFoundError(MakerError):
    """Raised when a requested resource does not exist."""


class ValidationError(MakerError):
    """Raised when user input is invalid."""


class GenerationError(MakerError):
    """Raised when agent generation or artifact writing fails."""

