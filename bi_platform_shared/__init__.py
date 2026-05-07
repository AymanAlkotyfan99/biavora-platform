"""
bi_platform_shared
==================

Single source of truth for cross-service contracts, security primitives, and
infrastructure helpers used by every microservice in the BI Agentic Platform.

This package replaces the duplicated copies of the following primitives that
were previously scattered across services:

  * Pydantic data contracts for the agent pipeline (intent, chart, pipeline,
    execution, trace).
  * Audio validation constants (extensions, size cap, duration cap).
  * Predictive-question detector (Arabic / English / French keywords).
  * DRF permission classes (IsManager, IsAnalyst, IsExecutive,
    IsManagerOrAnalyst).
  * HTTP client with retry, circuit breaker, and W3C trace context
    propagation.

Every microservice is expected to install this package as a local path
dependency in its requirements file and import from
``bi_platform_shared.<subpackage>`` instead of redefining the same logic
locally.
"""

from __future__ import annotations

__version__ = "1.0.0"

__all__ = ["__version__"]
