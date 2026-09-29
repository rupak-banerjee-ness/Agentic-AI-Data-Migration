"""LangGraph orchestrator: Discover -> ... -> Verify -> Done/Rollback (architecture.md §6).

Phase 1 scope: every node is a stub that logs and advances ``current_phase`` —
no real agent/tool-adapter logic yet (that lands in later phases). The graph
topology, human-review interrupts, and bounded-retry wiring are real.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from agents.assessment_agent import run_discovery
from agents.planner_agent import build_plan
from orchestrator import connection_registry
from orchestrator.retry import with_retry
from orchestrator.state import (
    ApprovalRecord,
    CodeRefactorResult,
    DataMigrationResult,
    DeploymentStatus,
    JobStatus,
    MigrationPlan,
    MigrationState,
    ReviewDecision,
    TestReport,
    TranslationResult,
    ValidationReport,
)

logger = logging.getLogger(__name__)


def _log_phase(state: MigrationState, phase: str) -> None:
    logger.info("[job=%s] entering phase=%s (stub)", state.job_id, phase)


def _resume_field(decision: Any, key: str, default: str) -> str:
    """Pull a field out of the reviewer's resume payload, tolerating bad input."""
    if isinstance(decision, dict):
        return decision.get(key, default)
    return default


# --- Discovery / planning ----------------------------------------------------


def _discover(state: MigrationState) -> dict[str, Any]:
    _log_phase(state, "Discover")
    connections = connection_registry.get(state.job_id)
    if connections is None:
        raise RuntimeError(
            f"no registered connection config for job {state.job_id} — the API "
            "process may have restarted before Discover ran; recreate the job"
        )
    source_connection, _target_connection = connections
    discovery = run_discovery(
        state.job_id, state.dialects.source, state.dialects.target, source_connection
    )
    connection_registry.discard(state.job_id)
    return {
        "current_phase": "Discover",
        "status": JobStatus.RUNNING.value,
        "discovery": discovery.model_dump(),
    }


def _analyse(state: MigrationState) -> dict[str, Any]:
    _log_phase(state, "Analyse")
    catalog = state.discovery.object_catalog if state.discovery else []
    counts = Counter(entry["object_type"] for entry in catalog)
    logger.info(
        "[job=%s] catalog: %d tables, %d views, %d procedures, %d functions, %d triggers",
        state.job_id,
        counts.get("table", 0),
        counts.get("view", 0),
        counts.get("procedure", 0),
        counts.get("function", 0),
        counts.get("trigger", 0),
    )
    return {"current_phase": "Analyse", "status": JobStatus.RUNNING.value}


def _plan(state: MigrationState) -> dict[str, Any]:
    _log_phase(state, "Plan")
    if state.discovery is None:
        plan = state.plan or MigrationPlan()
    else:
        plan = build_plan(state.discovery, state.dialects.source, state.dialects.target)
    return {
        "current_phase": "Plan",
        "status": JobStatus.PAUSED.value,  # next node is the HumanReviewPlan gate
        "plan": plan.model_dump(),
    }


def _human_review_plan(state: MigrationState) -> dict[str, Any]:
    decision = interrupt(
        {
            "type": "HumanReviewPlan",
            "phase": "HumanReviewPlan",
            "prompt": "Review the migration plan: approve, modify, or reject.",
            "plan": state.plan.model_dump() if state.plan else None,
        }
    )
    choice = _resume_field(decision, "decision", ReviewDecision.REJECT.value)
    record = ApprovalRecord(
        phase="HumanReviewPlan",
        decision=choice,
        reviewer=_resume_field(decision, "reviewer", "unknown"),
        comment=decision.get("comment") if isinstance(decision, dict) else None,
    )
    return {
        "current_phase": "HumanReviewPlan",
        "status": (
            JobStatus.ABORTED.value
            if choice == ReviewDecision.REJECT.value
            else JobStatus.RUNNING.value
        ),
        "approvals": [a.model_dump() for a in state.approvals] + [record.model_dump()],
        "plan_decision": choice,
    }


def _route_after_plan_review(state: MigrationState) -> str:
    return {
        ReviewDecision.APPROVE.value: "Transform",
        ReviewDecision.MODIFY.value: "Plan",
    }.get(state.plan_decision or "", END)


# --- Translation / refactor / data migration ---------------------------------


def _transform(state: MigrationState) -> dict[str, Any]:
    _log_phase(state, "Transform")
    return {"current_phase": "Transform", "status": JobStatus.RUNNING.value}


def _generate(state: MigrationState) -> dict[str, Any]:
    _log_phase(state, "Generate")
    # TODO(Phase 4): replace with Schema Agent / cracksql_adapter output.
    return {
        "current_phase": "Generate",
        "status": JobStatus.RUNNING.value,
        "schema_translation": (state.schema_translation or TranslationResult()).model_dump(),
    }


def _code_refactor(state: MigrationState) -> dict[str, Any]:
    _log_phase(state, "CodeRefactor")
    # TODO(Phase 6): replace with Code Agent / openrewrite+aider adapter output.
    return {
        "current_phase": "CodeRefactor",
        "status": JobStatus.RUNNING.value,
        "code_refactor": (state.code_refactor or CodeRefactorResult()).model_dump(),
    }


def _data_migrate(state: MigrationState) -> dict[str, Any]:
    _log_phase(state, "DataMigrate")
    # TODO(Phase 5): replace with Data Agent / seatunnel_adapter output.
    return {
        "current_phase": "DataMigrate",
        "status": JobStatus.RUNNING.value,
        "data_migration": (state.data_migration or DataMigrationResult()).model_dump(),
    }


def _validate(state: MigrationState) -> dict[str, Any]:
    _log_phase(state, "Validate")
    # TODO(Phase 7): replace with Validation Agent / checksum_adapter output.
    return {
        "current_phase": "Validate",
        "status": JobStatus.PAUSED.value,  # next node is the HumanReviewValidation gate
        "validation": (state.validation or ValidationReport(overall_status="PASS")).model_dump(),
    }


def _human_review_validation(state: MigrationState) -> dict[str, Any]:
    decision = interrupt(
        {
            "type": "HumanReviewValidation",
            "phase": "HumanReviewValidation",
            "prompt": "Review the validation report: approve, retry data migration, or reject.",
            "validation": state.validation.model_dump() if state.validation else None,
        }
    )
    choice = _resume_field(decision, "decision", ReviewDecision.REJECT.value)
    record = ApprovalRecord(
        phase="HumanReviewValidation",
        decision=choice,
        reviewer=_resume_field(decision, "reviewer", "unknown"),
        comment=decision.get("comment") if isinstance(decision, dict) else None,
    )
    return {
        "current_phase": "HumanReviewValidation",
        "status": (
            JobStatus.ABORTED.value
            if choice == ReviewDecision.REJECT.value
            else JobStatus.RUNNING.value
        ),
        "approvals": [a.model_dump() for a in state.approvals] + [record.model_dump()],
        "validation_decision": choice,
    }


def _route_after_validation_review(state: MigrationState) -> str:
    return {
        ReviewDecision.APPROVE.value: "Test",
        ReviewDecision.MODIFY.value: "DataMigrate",
    }.get(state.validation_decision or "", END)


# --- Test / cutover / verify --------------------------------------------------


def _test(state: MigrationState) -> dict[str, Any]:
    _log_phase(state, "Test")
    # TODO(Phase 7): replace with generated/executed migration test cases.
    report = state.test_report or TestReport(overall_status="PASS")
    next_status = (
        JobStatus.PAUSED.value if report.overall_status == "PASS" else JobStatus.RUNNING.value
    )
    return {"current_phase": "Test", "status": next_status, "test_report": report.model_dump()}


def _route_after_test(state: MigrationState) -> str:
    status = state.test_report.overall_status if state.test_report else "FAIL"
    return "HumanReviewCutover" if status == "PASS" else "Validate"


def _human_review_cutover(state: MigrationState) -> dict[str, Any]:
    decision = interrupt(
        {
            "type": "HumanReviewCutover",
            "phase": "HumanReviewCutover",
            "prompt": "Approve cutover to the new deployment, or reject.",
            "test_report": state.test_report.model_dump() if state.test_report else None,
        }
    )
    choice = _resume_field(decision, "decision", ReviewDecision.REJECT.value)
    record = ApprovalRecord(
        phase="HumanReviewCutover",
        decision=choice,
        reviewer=_resume_field(decision, "reviewer", "unknown"),
        comment=decision.get("comment") if isinstance(decision, dict) else None,
    )
    return {
        "current_phase": "HumanReviewCutover",
        "status": (
            JobStatus.ABORTED.value
            if choice == ReviewDecision.REJECT.value
            else JobStatus.RUNNING.value
        ),
        "approvals": [a.model_dump() for a in state.approvals] + [record.model_dump()],
        "cutover_decision": choice,
    }


def _route_after_cutover_review(state: MigrationState) -> str:
    return "Cutover" if state.cutover_decision == ReviewDecision.APPROVE.value else END


def _cutover(state: MigrationState) -> dict[str, Any]:
    _log_phase(state, "Cutover")
    return {"current_phase": "Cutover", "status": JobStatus.RUNNING.value}


def _verify(state: MigrationState) -> dict[str, Any]:
    _log_phase(state, "Verify")
    # TODO(Phase 8): replace with real post-cutover health-check gating.
    return {
        "current_phase": "Verify",
        "status": JobStatus.RUNNING.value,
        "deployment": DeploymentStatus(status="HEALTHY").model_dump(),
    }


def _route_after_verify(state: MigrationState) -> str:
    healthy = bool(state.deployment and state.deployment.status == "HEALTHY")
    return "Done" if healthy else "Rollback"


def _done(state: MigrationState) -> dict[str, Any]:
    _log_phase(state, "Done")
    return {"current_phase": "Done", "status": JobStatus.DONE.value}


def _rollback(state: MigrationState) -> dict[str, Any]:
    _log_phase(state, "Rollback")
    return {"current_phase": "Rollback", "status": JobStatus.ROLLED_BACK.value}


# Nodes wrapping an LLM call or external tool-adapter invocation get the bounded
# retry policy (architecture.md §6.1); pure in-process/orchestration nodes don't.
_RETRYABLE_NODES: dict[str, Any] = {
    "Discover": _discover,
    "Plan": _plan,
    "Transform": _transform,
    "Generate": _generate,
    "CodeRefactor": _code_refactor,
    "DataMigrate": _data_migrate,
    "Test": _test,
    "Cutover": _cutover,
}


def build_state_graph() -> StateGraph:
    """Assemble the (uncompiled) StateGraph with all nodes/edges from architecture.md §6."""
    graph = StateGraph(MigrationState)

    graph.add_node("Discover", with_retry("Discover", _RETRYABLE_NODES["Discover"]))
    graph.add_node("Analyse", _analyse)
    graph.add_node("Plan", with_retry("Plan", _RETRYABLE_NODES["Plan"]))
    graph.add_node("HumanReviewPlan", _human_review_plan)
    graph.add_node("Transform", with_retry("Transform", _RETRYABLE_NODES["Transform"]))
    graph.add_node("Generate", with_retry("Generate", _RETRYABLE_NODES["Generate"]))
    graph.add_node("CodeRefactor", with_retry("CodeRefactor", _RETRYABLE_NODES["CodeRefactor"]))
    graph.add_node("DataMigrate", with_retry("DataMigrate", _RETRYABLE_NODES["DataMigrate"]))
    graph.add_node("Validate", _validate)
    graph.add_node("HumanReviewValidation", _human_review_validation)
    graph.add_node("Test", with_retry("Test", _RETRYABLE_NODES["Test"]))
    graph.add_node("HumanReviewCutover", _human_review_cutover)
    graph.add_node("Cutover", with_retry("Cutover", _RETRYABLE_NODES["Cutover"]))
    graph.add_node("Verify", _verify)
    graph.add_node("Done", _done)
    graph.add_node("Rollback", _rollback)

    graph.add_edge(START, "Discover")
    graph.add_edge("Discover", "Analyse")
    graph.add_edge("Analyse", "Plan")
    graph.add_edge("Plan", "HumanReviewPlan")
    graph.add_conditional_edges(
        "HumanReviewPlan",
        _route_after_plan_review,
        {"Transform": "Transform", "Plan": "Plan", END: END},
    )
    graph.add_edge("Transform", "Generate")
    graph.add_edge("Generate", "CodeRefactor")
    graph.add_edge("CodeRefactor", "DataMigrate")
    graph.add_edge("DataMigrate", "Validate")
    graph.add_edge("Validate", "HumanReviewValidation")
    graph.add_conditional_edges(
        "HumanReviewValidation",
        _route_after_validation_review,
        {"Test": "Test", "DataMigrate": "DataMigrate", END: END},
    )
    graph.add_conditional_edges(
        "Test",
        _route_after_test,
        {"HumanReviewCutover": "HumanReviewCutover", "Validate": "Validate"},
    )
    graph.add_conditional_edges(
        "HumanReviewCutover",
        _route_after_cutover_review,
        {"Cutover": "Cutover", END: END},
    )
    graph.add_edge("Cutover", "Verify")
    graph.add_conditional_edges(
        "Verify",
        _route_after_verify,
        {"Done": "Done", "Rollback": "Rollback"},
    )
    graph.add_edge("Done", END)
    graph.add_edge("Rollback", END)

    return graph


def compile_graph(checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    """Compile the graph, optionally wired to a checkpointer for pause/resume."""
    return build_state_graph().compile(checkpointer=checkpointer)
