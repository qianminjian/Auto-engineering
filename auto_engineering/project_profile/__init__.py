"""宿主无关的项目能力契约与解析入口。"""

from auto_engineering.project_profile.config_provider import AeConfigProvider
from auto_engineering.project_profile.legacy_provider import LegacyInitProvider
from auto_engineering.project_profile.models import (
    PROJECT_PROFILE_SCHEMA_VERSION,
    ProfileEvidence,
    ProjectProfile,
    ProjectProfileError,
    ProjectProfileErrorCode,
    ProjectResolution,
)
from auto_engineering.project_profile.providers import (
    LocalProbeProvider,
    ProfileContribution,
    ProjectProfileProvider,
    detect_browser_capability,
)
from auto_engineering.project_profile.resolver import (
    ProjectProfileResolution,
    ProjectProfileResolver,
    ResolutionStatus,
)

__all__ = [
    "PROJECT_PROFILE_SCHEMA_VERSION",
    "AeConfigProvider",
    "LegacyInitProvider",
    "LocalProbeProvider",
    "ProfileContribution",
    "ProfileEvidence",
    "ProjectProfile",
    "ProjectProfileError",
    "ProjectProfileErrorCode",
    "ProjectProfileProvider",
    "ProjectProfileResolution",
    "ProjectProfileResolver",
    "ProjectResolution",
    "ResolutionStatus",
    "detect_browser_capability",
]
