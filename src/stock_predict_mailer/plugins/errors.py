"""Plugin failures that must reach the caller instead of becoming a quiet fallback.

Every one of them is non-retryable: a wrong manifest, a missing optional extra or
an undeclared id never fixes itself on a second attempt. The shape matches
``ServiceError`` so the CLI can print one JSON envelope for both.
"""
from __future__ import annotations


class PluginError(Exception):
    """A plugin cannot be used; surfacing this is the contract, not a courtesy."""

    code = "PLUGIN_ERROR"

    def __init__(self, message):
        super().__init__(message)
        self.message = message
        self.retryable = False

    def as_dict(self):
        return {"error": {"code": self.code, "message": self.message, "retryable": self.retryable}}


class PluginNotFound(PluginError):
    """The id is absent from the built-in whitelist."""

    code = "PLUGIN_NOT_FOUND"


class PluginIncompatible(PluginError):
    """The declaration itself is malformed or speaks another API version."""

    code = "PLUGIN_INCOMPATIBLE"


class PluginKindMismatch(PluginError):
    """The id exists but does not provide the requested kind of extension."""

    code = "PLUGIN_KIND_MISMATCH"


class PluginMissingDependency(PluginError):
    """A declared optional extra is not installed in this environment."""

    code = "PLUGIN_MISSING_DEPENDENCY"
