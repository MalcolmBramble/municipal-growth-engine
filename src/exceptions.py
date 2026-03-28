"""Custom exception hierarchy for municipal-growth-engine."""


class MunicipalGrowthError(Exception):
    """Base exception for all municipal-growth-engine errors."""


class ResolverError(MunicipalGrowthError):
    """Raised when a city cannot be resolved to FIPS codes."""


class CensusAPIError(MunicipalGrowthError):
    """Raised when the Census API returns an error or unexpected response."""


class StorageError(MunicipalGrowthError):
    """Raised when a database operation fails."""
