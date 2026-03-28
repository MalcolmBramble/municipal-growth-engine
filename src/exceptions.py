"""Custom exception hierarchy for municipal-growth-engine."""


class MunicipalGrowthError(Exception):
    """Base exception for all municipal-growth-engine errors."""


class ResolverError(MunicipalGrowthError):
    """Raised when a city cannot be resolved to FIPS codes."""


class CensusAPIError(MunicipalGrowthError):
    """Raised when the Census API returns an error or unexpected response."""


class StorageError(MunicipalGrowthError):
    """Raised when a database operation fails."""


class BLSAPIError(MunicipalGrowthError):
    """Raised when the BLS API returns an error or unexpected response."""


class HousingDataError(MunicipalGrowthError):
    """Raised when housing CSV parsing fails."""


class WalkScoreError(MunicipalGrowthError):
    """Raised when the Walk Score API or geocoding fails."""


class FEMADataError(MunicipalGrowthError):
    """Raised when FEMA NRI CSV parsing fails."""
