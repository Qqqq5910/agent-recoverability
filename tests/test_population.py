"""Tests for population accounting, deterministic selection, and the 2x2 table.

Two invariants matter more than the arithmetic here. Selection must be a
function of ``task_id`` alone, so the analysed population cannot be shaped by
the outcomes it is later used to measure; and the contingency table must
account for every analysed run exactly once, so a proportion's denominator is
never quietly smaller than the population it claims to describe.
"""

from __future__ import annotations

import inspect
import json
import random
import sys
from pathlib import Path

import pytest

from recoverability.analysis import contingency_table, error_family_outcomes, wilson_interval
from recoverability.population import (
    ExclusionReason,
    PopulationAccounting,
    deterministic_subset,
)
from recoverability.schema import (
    ActionKind,
    ObservationStatus,
    RunRecord,
    StepRecord,
    TerminationReason,
    VerdictSource,
)

SUMMARY = Path(__file__).parents[1] / "docs" / "artifacts" / "phase1b_population_summary.json"


def make_run(
    task_id: str,
    *,
    final_success: bool | None,
    error_signature: str | None = None,
) -> RunRecord:
    """A one-step run, optionally carrying a single error event."""
    status = ObservationStatus.ERROR if error_signature else ObservationStatus.OK
    step = StepRecord(
        task_id=task_id,
        run_id=f"run-{task_id}",
        agent_name="mini-SWE-agent",
        model_name="claude-4-sonnet-20250514",
        step_index=0,
        trajectory_length_so_far=1,
        action="python -m pytest -q",
        observation="1 failed" if error_signature else "1 passed",
        action_kind=ActionKind.TEST_RUN,
        observation_status=status,
        error_signature=error_signature,
    )
    if final_success is None:
        termination = TerminationReason.AGENT_SUBMITTED
        verdict_source = VerdictSource.UNKNOWN
    else:
        termination = (
            TerminationReason.SUCCESS if final_success else TerminationReason.BENCHMARK_FAILURE
        )
        verdict_source = VerdictSource.SWE_BENCH_REPORT
    return RunRecord(
        task_id=task_id,
        run_id=f"run-{task_id}",
        agent_name="mini-SWE-agent",
        model_name="claude-4-sonnet-20250514",
        steps=[step],
        final_success=final_success,
        termination_reason=termination,
        verdict_source=verdict_source,
    )


# --- Selection is blind to outcome ----------------------------------------


def test_subset_selection_takes_ids_not_runs():
    """A verdict cannot influence selection if it is not in the signature."""
    parameters = inspect.signature(deterministic_subset).parameters
    assert set(parameters) == {"task_ids", "limit"}


def test_subset_is_the_sort_ordered_prefix():
    ids = ["c__c-3", "a__a-1", "b__b-2"]
    assert deterministic_subset(ids, 2) == ["a__a-1", "b__b-2"]


def test_subset_ignores_input_order():
    """Shuffling the input cannot change which ids are analysed."""
    ids = [f"proj__proj-{i}" for i in range(50)]
    expected = deterministic_subset(sorted(ids), 10)
    for seed in range(5):
        shuffled = ids[:]
        random.Random(seed).shuffle(shuffled)
        assert deterministic_subset(shuffled, 10) == expected


def test_no_limit_keeps_the_whole_population():
    ids = ["b__b-2", "a__a-1"]
    assert deterministic_subset(ids, None) == ["a__a-1", "b__b-2"]


def test_limit_beyond_the_population_is_not_an_error():
    assert deterministic_subset(["a__a-1"], 99) == ["a__a-1"]


# --- Accounting reconciles -------------------------------------------------


def test_accounting_reconciles_when_every_join_is_accounted_for():
    accounting = PopulationAccounting(n_joined_runs=10, n_analyzed_runs=8)
    accounting.exclude("a__a-1", ExclusionReason.MALFORMED)
    accounting.exclude("a__a-2", ExclusionReason.EXTERNAL_INTERRUPTION)
    assert accounting.reconciles()


def test_accounting_fails_to_reconcile_on_a_silent_drop():
    """A run that vanished between join and analysis must be detectable."""
    accounting = PopulationAccounting(n_joined_runs=10, n_analyzed_runs=8)
    assert not accounting.reconciles()


def test_pre_join_exclusions_are_not_part_of_the_identity():
    accounting = PopulationAccounting(n_joined_runs=5, n_analyzed_runs=5)
    accounting.exclude("a__a-9", ExclusionReason.MISSING_VERDICT)
    accounting.exclude("a__a-8", ExclusionReason.MISSING_TRAJECTORY)
    assert accounting.reconciles()


def test_exclusions_record_task_ids_not_just_counts():
    accounting = PopulationAccounting()
    accounting.exclude("z__z-2", ExclusionReason.MALFORMED)
    accounting.exclude("z__z-1", ExclusionReason.MALFORMED)
    assert accounting.to_dict()["excluded_task_ids"][ExclusionReason.MALFORMED] == [
        "z__z-1",
        "z__z-2",
    ]


# --- Contingency table ----------------------------------------------------


@pytest.fixture
def population() -> list[RunRecord]:
    return [
        make_run("a__a-1", final_success=True, error_signature="test_failure:pytest"),
        make_run("a__a-2", final_success=True, error_signature="python_exception"),
        make_run("a__a-3", final_success=True),
        make_run("a__a-4", final_success=False, error_signature="test_failure:pytest"),
        make_run("a__a-5", final_success=False),
    ]


def test_contingency_cells_are_counted_correctly(population):
    table = contingency_table(population)
    assert (table.success_with_error, table.success_without_error) == (2, 1)
    assert (table.failure_with_error, table.failure_without_error) == (1, 1)


def test_contingency_margins_sum_to_the_total(population):
    table = contingency_table(population)
    assert table.n_success + table.n_failure == table.total
    assert table.n_with_error + table.n_without_error == table.total
    assert table.total == len(population)


def test_every_verdict_bearing_run_lands_in_exactly_one_cell(population):
    table = contingency_table(population)
    cells = (
        table.success_with_error,
        table.success_without_error,
        table.failure_with_error,
        table.failure_without_error,
    )
    assert sum(cells) == len([r for r in population if r.final_success is not None])


def test_runs_without_a_verdict_are_not_folded_into_a_cell(population):
    """An unknown verdict belongs in the accounting, not in a failure cell."""
    table = contingency_table([*population, make_run("a__a-6", final_success=None)])
    assert table.total == len(population)


def test_proportions_carry_their_denominators(population):
    table = contingency_table(population)
    assert str(table.p_success_given_error()) == "2 / 3 = 66.7%"
    assert table.p_error_given_failure().to_dict()["denominator"] == 2


def test_proportion_of_an_empty_cell_is_undefined_not_zero():
    table = contingency_table([])
    assert table.p_success_given_error().value is None
    assert table.p_success_given_error().ci95 is None


def test_wilson_interval_brackets_the_point_estimate():
    lower, upper = wilson_interval(232, 375)
    assert lower < 232 / 375 < upper


def test_wilson_interval_stays_inside_the_unit_interval():
    for successes, total in ((0, 10), (10, 10), (1, 500)):
        lower, upper = wilson_interval(successes, total)
        assert 0.0 <= lower <= upper <= 1.0


def test_wilson_interval_of_no_data_constrains_nothing():
    assert wilson_interval(0, 0) == (0.0, 1.0)


# --- Error families -------------------------------------------------------


def test_error_family_rows_split_by_outcome(population):
    families = error_family_outcomes(population)
    assert families["test_failure"] == {
        "n_runs_with_error_type": 2,
        "n_success": 1,
        "n_failure": 1,
        "n_unknown": 0,
    }


def test_a_run_is_counted_once_per_distinct_family(population):
    """Family rows may overlap, so they must not be assumed to sum to the total."""
    families = error_family_outcomes(population)
    assert sum(row["n_runs_with_error_type"] for row in families.values()) >= len(population) - 2


# --- The committed artifact -----------------------------------------------


@pytest.fixture
def summary() -> dict:
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def test_committed_summary_reconciles(summary):
    assert summary["population"]["reconciles"] is True


def test_committed_contingency_sums_to_the_analysed_population(summary):
    table = summary["contingency_table"]
    cells = (
        table["success_with_error"],
        table["success_without_error"],
        table["failure_with_error"],
        table["failure_without_error"],
    )
    assert sum(cells) == table["total"] == summary["population"]["n_analyzed_runs"]


def test_committed_summary_declares_no_recovery_labels(summary):
    assert summary["recovery_labels_computed"] is False


def test_recovery_candidates_are_not_called_recoveries(summary):
    serialised = json.dumps(summary)
    assert "self_recovered" not in serialised
    assert summary["recovery_candidates"]["label"] == "SUCCESS_AFTER_OBSERVED_ERROR"


def test_offline_fields_are_labelled_in_the_committed_artifact(summary):
    assert "NOT PREFIX SAFE" in summary["offline_descriptive"]["_warning"]


def test_committed_summary_carries_no_trajectory_text(summary):
    """Aggregates only: no command, observation, or diff may be serialised."""
    serialised = json.dumps(summary)
    for marker in ("<returncode>", "<output>", "THOUGHT:", "diff --git", "```bash"):
        assert marker not in serialised
    for value in _strings(summary):
        assert "\n" not in value, f"multi-line value looks like raw text: {value[:40]!r}"


def test_summary_is_stable_across_reruns_and_input_order(population):
    """Re-ingesting the same runs must reproduce the artifact byte for byte.

    Order independence matters because the aggregate is the committed record:
    if a directory listing came back shuffled, the artifact would still have to
    be identical, otherwise its diff would imply the data had moved.
    """
    sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
    from ingest_phase1b import build_population_summary

    def render(runs: list[RunRecord]) -> str:
        accounting = PopulationAccounting(n_joined_runs=len(runs), n_analyzed_runs=len(runs))
        summary = build_population_summary(runs, accounting, [])
        return json.dumps(summary, indent=2, sort_keys=True)

    first = render(population)
    assert render(population) == first
    shuffled = population[:]
    random.Random(0).shuffle(shuffled)
    assert render(shuffled) == first


def _strings(node: object) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for value in node.values() for s in _strings(value)]
    if isinstance(node, list):
        return [s for item in node for s in _strings(item)]
    return []
