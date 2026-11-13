"""Shared example records for tests: load what flag_it.fixtures.build wrote to fixtures/.

    from flag_it import fixtures
    snap = fixtures.snapshot("receipt_mismatch")
    run = fixtures.decision_run("agent_flagged")
    run_flags = fixtures.flags("agent_flagged")

What each fixture covers: fixtures/catalog.md. Every loader validates with the contract models,
so a stale file fails loudly. Collections are read-only and cached, so tests can't change them
for each other.
"""

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, TypeVar

from flag_it.contracts.decide import AgentOutput, DecisionRun, Flag
from flag_it.contracts.jobs import InvestigateJob, ReadReceiptJob, load_job
from flag_it.contracts.review import ReviewOutcome
from flag_it.contracts.snapshot import CombinedExpenseSnapshot, load_snapshot
from flag_it.contracts.transactions import RawTransaction
from flag_it.db.rows import ReceiptFile

_REPO_FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"

T = TypeVar("T")


def fixtures_dir() -> Path:
    """FLAG_IT_FIXTURES_PATH if set (installed copies), else the repo's fixtures/ folder."""
    return Path(os.environ.get("FLAG_IT_FIXTURES_PATH", _REPO_FIXTURES))


def _read(file: str) -> dict[str, Any]:
    return json.loads((fixtures_dir() / file).read_text())


def _frozen(items: dict[str, T]) -> Mapping[str, T]:
    return MappingProxyType(items)


def _get(mapping: Mapping[str, T], name: str, kind: str) -> T:
    try:
        return mapping[name]
    except KeyError:
        raise KeyError(f"no {kind} fixture {name!r}; known: {', '.join(sorted(mapping))}") from None


@cache
def raw_transactions() -> Mapping[str, RawTransaction]:
    return _frozen({n: RawTransaction.model_validate(d) for n, d in _read("raw_transactions.json").items()})


@cache
def receipt_files() -> Mapping[str, ReceiptFile]:
    return _frozen({n: ReceiptFile.model_validate(d) for n, d in _read("receipt_files.json").items()})


@cache
def snapshots() -> Mapping[str, CombinedExpenseSnapshot]:
    return _frozen({n: load_snapshot(d) for n, d in _read("snapshots.json").items()})


def snapshot(name: str) -> CombinedExpenseSnapshot:
    return _get(snapshots(), name, "snapshot")


@cache
def decision_runs() -> Mapping[str, DecisionRun]:
    return _frozen({n: DecisionRun.model_validate(d) for n, d in _read("decision_runs.json").items()})


def decision_run(name: str) -> DecisionRun:
    return _get(decision_runs(), name, "decision run")


def snapshot_for(run: DecisionRun) -> CombinedExpenseSnapshot:
    return next(s for s in snapshots().values() if s.snapshot_id == run.snapshot_id)


@cache
def _flags() -> Mapping[str, tuple[Flag, ...]]:
    return _frozen({n: tuple(Flag.model_validate(f) for f in fs) for n, fs in _read("flags.json").items()})


def flags(run_name: str) -> tuple[Flag, ...]:
    """The flags of one run, in the order the builder lists them. Empty when the run has none."""
    _get(decision_runs(), run_name, "decision run")
    return _flags().get(run_name, ())


@cache
def review_outcomes() -> Mapping[str, ReviewOutcome]:
    return _frozen({n: ReviewOutcome.model_validate(d) for n, d in _read("review_outcomes.json").items()})


@cache
def agent_outputs() -> Mapping[str, AgentOutput]:
    return _frozen({n: AgentOutput.model_validate(d) for n, d in _read("agent_outputs.json").items()})


def agent_output(name: str) -> AgentOutput:
    return _get(agent_outputs(), name, "agent output")


@dataclass(frozen=True)
class InvalidAgentOutput:
    output: Mapping[str, Any]  # raw JSON, as the LLM would return it
    error: str  # a fragment of the ValidationError it must raise


def invalid_agent_outputs() -> Mapping[str, InvalidAgentOutput]:
    """Not cached: each call re-reads the file, so a test that edits an output can't affect another."""
    return _frozen(
        {n: InvalidAgentOutput(output=c["output"], error=c["error"]) for n, c in _read("agent_outputs_invalid.json").items()}
    )


@cache
def investigate_jobs() -> Mapping[str, InvestigateJob]:
    return _frozen({n: load_job(InvestigateJob, d) for n, d in _read("jobs.json")["investigate"].items()})


@cache
def read_receipt_jobs() -> Mapping[str, ReadReceiptJob]:
    return _frozen({n: load_job(ReadReceiptJob, d) for n, d in _read("jobs.json")["read_receipt"].items()})
