from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import re
import unicodedata


class Eligibility(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ReviewContext:
    reviewer_id: str
    project_id: str
    target_digest: str
    scope_id: str
    author_ids: tuple[str, ...] | None = None
    material_contributor_ids: tuple[str, ...] | None = None
    delegated_from_ids: tuple[str, ...] | None = None
    active_write_owner_ids: tuple[str, ...] | None = None
    provenance_complete: bool = False


@dataclass(frozen=True)
class EligibilityResult:
    outcome: Eligibility
    reason_codes: tuple[str, ...]



_DIGEST = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64}|sha1:[0-9a-fA-F]{40}|sha256:[0-9a-fA-F]{64})")


def _valid_id(value: object) -> bool:
    return (type(value) is str and bool(value) and value == value.strip()
            and not any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in value))


def _valid_digest(value: object) -> bool:
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def evaluate_reviewer(context: ReviewContext) -> EligibilityResult:
    if type(context) is not ReviewContext:
        return EligibilityResult(Eligibility.UNKNOWN, ("INCOMPLETE_CONTEXT",))
    try:
        context = ReviewContext(
            context.reviewer_id, context.project_id, context.target_digest,
            context.scope_id, context.author_ids, context.material_contributor_ids,
            context.delegated_from_ids, context.active_write_owner_ids,
            context.provenance_complete)
    except AttributeError:
        return EligibilityResult(Eligibility.UNKNOWN, ("INCOMPLETE_CONTEXT",))
    if (not all(_valid_id(value) for value in (context.reviewer_id, context.project_id, context.scope_id))
            or not _valid_digest(context.target_digest)):
        return EligibilityResult(Eligibility.UNKNOWN, ("INCOMPLETE_CONTEXT",))
    if context.provenance_complete is not True:
        return EligibilityResult(Eligibility.UNKNOWN, ("INCOMPLETE_PROVENANCE",))

    # Each list must be supplied, including explicit empty histories. Completeness
    # attests that delegated_from_ids contains ALL resolved delegation ancestors.
    histories = (context.author_ids, context.material_contributor_ids,
                 context.delegated_from_ids, context.active_write_owner_ids)
    if any(type(ids) is not tuple or
           any(not _valid_id(actor) for actor in ids)
           for ids in histories):
        return EligibilityResult(Eligibility.UNKNOWN, ("INCOMPLETE_PROVENANCE",))
    if len(set(context.delegated_from_ids)) != len(context.delegated_from_ids):
        return EligibilityResult(Eligibility.UNKNOWN, ("AMBIGUOUS_DELEGATION",))

    blocked: list[str] = []
    reviewer = context.reviewer_id

    if reviewer in context.author_ids:
        blocked.append("SELF_REVIEW")
    if reviewer in context.material_contributor_ids:
        blocked.append("MATERIAL_CONTRIBUTOR")
    if reviewer in context.active_write_owner_ids:
        blocked.append("OVERLAPPING_ACTIVE_WRITE")
    ancestors = set(context.delegated_from_ids)
    excluded = set(context.author_ids) | set(context.material_contributor_ids) | set(context.active_write_owner_ids)
    if reviewer in ancestors or ancestors & excluded:
        blocked.append("DELEGATED_SELF_REVIEW")

    if blocked:
        return EligibilityResult(Eligibility.INELIGIBLE, tuple(sorted(set(blocked))))
    return EligibilityResult(Eligibility.ELIGIBLE, ("INDEPENDENCE_CONFIRMED",))


__version__ = "0.1.0"


def _synthetic_cases():
    base = ReviewContext("reviewer-b", "demo-project", "sha256:" + "b" * 64,
                         "module-a", ("author-a",), (), (), (), True)
    specifications = (
        ("independent", "ELIGIBLE", {}),
        ("unrelated_ancestor", "ELIGIBLE", {"delegated_from_ids": ("other",)}),
        ("unicode_identity", "ELIGIBLE", {"reviewer_id": "granskare-å"}),
        ("self_review", "INELIGIBLE", {"reviewer_id": "author-a"}),
        ("material_contributor", "INELIGIBLE", {"material_contributor_ids": ("reviewer-b",)}),
        ("active_writer", "INELIGIBLE", {"active_write_owner_ids": ("reviewer-b",)}),
        ("delegated_author", "INELIGIBLE", {"delegated_from_ids": ("author-a",)}),
        ("delegated_contributor", "INELIGIBLE", {
            "material_contributor_ids": ("parent",), "delegated_from_ids": ("parent",)}),
        ("delegated_writer", "INELIGIBLE", {
            "active_write_owner_ids": ("parent",), "delegated_from_ids": ("parent",)}),
        ("self_ancestor", "INELIGIBLE", {"delegated_from_ids": ("reviewer-b",)}),
        ("missing_history", "UNKNOWN", {"author_ids": None}),
        ("missing_attestation", "UNKNOWN", {"provenance_complete": False}),
        ("duplicate_ancestor", "UNKNOWN", {"delegated_from_ids": ("parent", "parent")}),
        ("moving_ref", "UNKNOWN", {"target_digest": "main"}),
        ("missing_scope", "UNKNOWN", {"scope_id": ""}),
        ("control_character", "UNKNOWN", {"reviewer_id": "reviewer\n"}),
    )
    return tuple((name, expected, replace(base, **changes))
                 for name, expected, changes in specifications)


def main(argv=None) -> int:
    """Bounded local JSON CLI; no network, approval recording or release action."""
    import argparse
    import hashlib
    import json
    from pathlib import Path
    import platform
    import statistics
    import sys
    from time import perf_counter_ns

    parser = argparse.ArgumentParser(description="Local reviewer independence decision")
    parser.add_argument("--version", action="version", version=__version__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--context", help="JSON file, or - for standard input (max 65536 bytes)")
    mode.add_argument("--demo", action="store_true", help="Run synthetic outcome cases")
    mode.add_argument("--benchmark", action="store_true", help="Measure synthetic cases locally")
    parser.add_argument("--iterations", type=int, default=100)
    args = parser.parse_args(argv)
    if not 1 <= args.iterations <= 10000:
        parser.error("iterations must be from 1 to 10000")
    if args.context is not None:
        try:
            if args.context == "-":
                data = sys.stdin.buffer.read(65537)
            else:
                with open(args.context, "rb") as source:
                    data = source.read(65537)
            if len(data) > 65536:
                raise ValueError("size")
            payload = json.loads(data.decode("utf-8"))
            required = {"reviewer_id", "project_id", "target_digest", "scope_id"}
            histories = {"author_ids", "material_contributor_ids", "delegated_from_ids",
                         "active_write_owner_ids"}
            allowed = required | histories | {"provenance_complete"}
            if type(payload) is not dict or not required <= payload.keys() or not payload.keys() <= allowed:
                raise ValueError("fields")
            for key in histories:
                if key in payload and payload[key] is not None:
                    if type(payload[key]) is not list:
                        raise ValueError("history")
                    payload[key] = tuple(payload[key])
            result = evaluate_reviewer(ReviewContext(**payload))
        except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
            print(json.dumps({"outcome": "UNKNOWN", "reason_codes": ["INVALID_CLI_INPUT"]}))
            return 2
        print(json.dumps({"outcome": result.outcome.value, "reason_codes": result.reason_codes}))
        return {Eligibility.ELIGIBLE: 0, Eligibility.INELIGIBLE: 1, Eligibility.UNKNOWN: 2}[result.outcome]

    rows = []
    mismatches = 0
    observations = 0
    for name, expected, context in _synthetic_cases():
        samples = []
        counts = {outcome.value: 0 for outcome in Eligibility}
        for _ in range(args.iterations if args.benchmark else 1):
            start = perf_counter_ns()
            result = evaluate_reviewer(context)
            samples.append(perf_counter_ns() - start)
            counts[result.outcome.value] += 1
            observations += 1
            mismatches += result.outcome.value != expected
        row = {"case_id": name, "expected": expected, "observed_counts": counts}
        if args.benchmark:
            ordered = sorted(samples)
            row["latency_ns"] = {"min": ordered[0], "median": statistics.median(ordered),
                                 "p95": ordered[(95 * len(ordered) + 99) // 100 - 1], "max": ordered[-1]}
        rows.append(row)
    report = {"synthetic_only": True, "version": __version__, "case_count": len(rows),
              "observation_count": observations, "mismatched_observations": mismatches, "cases": rows}
    if args.benchmark:
        report.update({"module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       "python_version": platform.python_version(), "iterations_per_case": args.iterations,
                       "clock": "perf_counter_ns", "warmup_iterations": 0,
                       "includes": "evaluate_reviewer and timer overhead", "p95_method": "nearest_rank"})
    print(json.dumps(report, sort_keys=True))
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
