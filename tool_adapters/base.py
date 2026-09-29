"""Abstract contract every tool adapter (CrackSQL, SeaTunnel, OpenRewrite, ...) must implement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AdapterConfig:
    """Normalized, validated configuration handed to `run()`."""

    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """Outcome of a single adapter invocation."""

    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class JobStatus:
    """Point-in-time status of a long-running adapter job."""

    job_id: str
    state: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class RollbackResult:
    """Outcome of a rollback attempt for a previously run adapter job."""

    success: bool
    detail: dict[str, Any] = field(default_factory=dict)


class BaseToolAdapter(ABC):
    """Plugin interface: agents call adapters generically through this contract only."""

    @abstractmethod
    def prepare(self, config: dict[str, Any]) -> AdapterConfig:
        """Validate and normalize raw job config into an `AdapterConfig`."""
        raise NotImplementedError

    @abstractmethod
    def run(self, config: AdapterConfig) -> ToolResult:
        """Execute the underlying tool and return its result."""
        raise NotImplementedError

    @abstractmethod
    def status(self, job_id: str) -> JobStatus:
        """Report the current status of a previously started job."""
        raise NotImplementedError

    @abstractmethod
    def rollback(self, job_id: str) -> RollbackResult:
        """Undo the effects of a previously run job, where supported."""
        raise NotImplementedError
