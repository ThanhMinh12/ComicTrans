class MangaWorkspaceError(Exception):
    """Base exception for expected workspace failures."""


class MissingDependencyError(MangaWorkspaceError):
    """Raised when an optional local engine dependency is not installed."""

    def __init__(self, package: str, install_hint: str) -> None:
        super().__init__(f"Missing dependency '{package}'. Install with: {install_hint}")
        self.package = package
        self.install_hint = install_hint
