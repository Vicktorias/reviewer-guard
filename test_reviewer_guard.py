import unittest

from reviewer_guard import Eligibility, ReviewContext, evaluate_reviewer


class ReviewerGuardTests(unittest.TestCase):
    def context(self, **changes):
        values = {
            "reviewer_id": "reviewer-b",
            "project_id": "demo-project",
            "target_digest": "sha256:" + "b" * 64,
            "scope_id": "module-a",
            "author_ids": ("author-a",),
            "material_contributor_ids": (),
            "delegated_from_ids": (),
            "active_write_owner_ids": (),
            "provenance_complete": True,
        }
        values.update(changes)
        return ReviewContext(**values)

    def test_independent_reviewer_is_eligible(self):
        self.assertEqual(evaluate_reviewer(self.context()).outcome, Eligibility.ELIGIBLE)

    def test_self_review_is_ineligible(self):
        result = evaluate_reviewer(self.context(reviewer_id="author-a"))
        self.assertEqual(result.outcome, Eligibility.INELIGIBLE)
        self.assertIn("SELF_REVIEW", result.reason_codes)

    def test_material_contributor_is_ineligible(self):
        result = evaluate_reviewer(self.context(material_contributor_ids=("reviewer-b",)))
        self.assertEqual(result.outcome, Eligibility.INELIGIBLE)

    def test_active_write_owner_is_ineligible(self):
        result = evaluate_reviewer(self.context(active_write_owner_ids=("reviewer-b",)))
        self.assertEqual(result.outcome, Eligibility.INELIGIBLE)

    def test_delegated_self_review_is_ineligible(self):
        result = evaluate_reviewer(self.context(delegated_from_ids=("reviewer-b",)))
        self.assertEqual(result.outcome, Eligibility.INELIGIBLE)

    def test_missing_provenance_is_unknown(self):
        result = evaluate_reviewer(self.context(provenance_complete=False))
        self.assertEqual(result.outcome, Eligibility.UNKNOWN)

    def test_delegation_ancestors_cannot_review_their_work(self):
        for history in ("author_ids", "material_contributor_ids", "active_write_owner_ids"):
            with self.subTest(history=history):
                result = evaluate_reviewer(self.context(delegated_from_ids=("parent", "grandparent"), **{history: ("grandparent",)}))
                self.assertEqual(result.outcome, Eligibility.INELIGIBLE)
                self.assertIn("DELEGATED_SELF_REVIEW", result.reason_codes)

    def test_independent_complete_delegation_is_eligible(self):
        self.assertEqual(evaluate_reviewer(self.context(delegated_from_ids=("independent-parent",))).outcome, Eligibility.ELIGIBLE)

    def test_omitted_provenance_is_unknown(self):
        context = ReviewContext("reviewer", "synthetic-project", "a" * 40, "module")
        self.assertEqual(evaluate_reviewer(context).outcome, Eligibility.UNKNOWN)

    def test_omitted_histories_cannot_be_asserted_complete(self):
        context = ReviewContext("reviewer", "synthetic-project", "a" * 40, "module", provenance_complete=True)
        self.assertEqual(evaluate_reviewer(context).outcome, Eligibility.UNKNOWN)
        for history in ("author_ids", "material_contributor_ids", "delegated_from_ids", "active_write_owner_ids"):
            with self.subTest(history=history):
                self.assertEqual(evaluate_reviewer(self.context(**{history: None})).outcome, Eligibility.UNKNOWN)

    def test_explicit_empty_complete_history_is_eligible(self):
        self.assertEqual(evaluate_reviewer(self.context(author_ids=())).outcome, Eligibility.ELIGIBLE)

    def test_ambiguous_or_incomplete_ancestry_fails_closed(self):
        for ancestors in (("parent", "parent"), ("",), (None,), "parent"):
            with self.subTest(ancestors=ancestors):
                self.assertEqual(evaluate_reviewer(self.context(delegated_from_ids=ancestors)).outcome, Eligibility.UNKNOWN)
        self.assertEqual(evaluate_reviewer(self.context(delegated_from_ids=("parent",), provenance_complete=False)).outcome, Eligibility.UNKNOWN)

    def test_truthy_unverified_attestation_is_unknown(self):
        self.assertEqual(evaluate_reviewer(self.context(provenance_complete="yes")).outcome, Eligibility.UNKNOWN)


    def test_malformed_scalar_context_fails_closed(self):
        cases = [
            {"target_digest": "main"}, {"target_digest": 123},
            {"reviewer_id": "   "}, {"project_id": "\t"}, {"scope_id": "\n"},
            {"reviewer_id": 123}, {"scope_id": 123}, {"scope_id": "module\x00a"},
        ]
        for field in ("reviewer_id", "project_id", "scope_id"):
            cases.extend({field: value} for value in (None, False, [], " padded", "padded ", "hidden\u200b", "bidi\u202e", "surrogate\ud800"))
        for changes in cases:
            with self.subTest(changes=changes):
                result = evaluate_reviewer(self.context(**changes))
                self.assertEqual(result.outcome, Eligibility.UNKNOWN)
                self.assertEqual(result.reason_codes, ("INCOMPLETE_CONTEXT",))

    def test_full_immutable_digest_forms_and_mutable_refs(self):
        for digest in ("a" * 40, "A" * 40, "b" * 64, "B" * 64, "sha1:" + "a" * 40, "sha256:" + "B" * 64):
            with self.subTest(digest=digest):
                self.assertEqual(evaluate_reviewer(self.context(target_digest=digest)).outcome, Eligibility.ELIGIBLE)
        for digest in ("main", "refs/heads/main", "latest", "sha256:demo-target", "sha256:" + "a" * 63, "sha1:" + "a" * 64, "x" * 40, "md5:" + "a" * 32, "a" * 40 + "\n", " " + "a" * 40, None, True, 123, ("a" * 40,)):
            with self.subTest(digest=digest):
                result = evaluate_reviewer(self.context(target_digest=digest))
                self.assertEqual(result.outcome, Eligibility.UNKNOWN)
                self.assertEqual(result.reason_codes, ("INCOMPLETE_CONTEXT",))

    def test_noncanonical_history_actor_ids_fail_closed(self):
        for field in ("author_ids", "material_contributor_ids", "delegated_from_ids", "active_write_owner_ids"):
            for value in (" author", "author ", "author\x00", "author\u200b", "author\u202e", "author\ud800", 123, True):
                with self.subTest(field=field, value=value):
                    result = evaluate_reviewer(self.context(**{field: (value,)}))
                    self.assertEqual(result.outcome, Eligibility.UNKNOWN)
                    self.assertEqual(result.reason_codes, ("INCOMPLETE_PROVENANCE",))

    def test_legitimate_unicode_ids_are_not_restricted_to_ascii(self):
        result = evaluate_reviewer(self.context(reviewer_id="granskare-Å", project_id="projekt-Ö", scope_id="modul-Ä"))
        self.assertEqual(result.outcome, Eligibility.ELIGIBLE)


class ReleaseBoundaryTests(unittest.TestCase):
    context = ReviewerGuardTests.context

    def test_dynamic_strings_and_tuples_cannot_hide_authorship(self):
        class HiddenTuple(tuple):
            def __contains__(self, item):
                return False

        class HiddenString(str):
            def strip(self):
                return self

            def __eq__(self, other):
                return self is other

            __hash__ = str.__hash__

        for changes in (
            {"reviewer_id": "author-a", "author_ids": HiddenTuple(("author-a",))},
            {"reviewer_id": HiddenString("author-a")},
            {"author_ids": (HiddenString("reviewer-b"),)},
            {"target_digest": HiddenString("a" * 40)},
        ):
            self.assertEqual(evaluate_reviewer(self.context(**changes)).outcome, Eligibility.UNKNOWN)

    def test_missing_and_dynamic_context_records_fail_closed(self):
        class DynamicContext(ReviewContext):
            pass

        for context in (None, object(), object.__new__(ReviewContext),
                        DynamicContext("r", "p", "a" * 40, "s", (), (), (), (), True)):
            self.assertEqual(evaluate_reviewer(context).outcome, Eligibility.UNKNOWN)


class CliTests(unittest.TestCase):
    def run_cli(self, *args, data=None):
        import subprocess
        import sys
        return subprocess.run([sys.executable, "-B", "-m", "reviewer_guard", *args],
                              input=data, capture_output=True, text=True)

    def payload(self, **changes):
        value = {"reviewer_id": "reviewer-b", "project_id": "demo", "target_digest": "b" * 40,
                 "scope_id": "module", "author_ids": ["author-a"], "material_contributor_ids": [],
                 "delegated_from_ids": [], "active_write_owner_ids": [], "provenance_complete": True}
        value.update(changes)
        return value

    def test_json_context_exit_contract(self):
        import json
        for changes, exit_code, outcome in (({}, 0, "ELIGIBLE"),
                ({"reviewer_id": "author-a"}, 1, "INELIGIBLE"),
                ({"provenance_complete": False}, 2, "UNKNOWN")):
            result = self.run_cli("--context", "-", data=json.dumps(self.payload(**changes)))
            self.assertEqual(result.returncode, exit_code, result.stderr)
            self.assertEqual(json.loads(result.stdout)["outcome"], outcome)
            self.assertNotIn("author-a", result.stdout)

    def test_malformed_oversized_or_unknown_input_never_echoes(self):
        import json
        samples = ("PRIVATE", "x" * 65537, "[]", "{" * 1200,
                   json.dumps(self.payload(secret="SYNTHETIC-PRIVATE")),
                   json.dumps(self.payload(author_ids={"secret": "SYNTHETIC-PRIVATE"})))
        for data in samples:
            result = self.run_cli("--context", "-", data=data)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)["outcome"], "UNKNOWN")
            self.assertNotIn("PRIVATE", result.stdout + result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_synthetic_demo_benchmark_and_version(self):
        import json
        for args, observations in ((("--demo",), 16), (("--benchmark", "--iterations", "2"), 32)):
            result = self.run_cli(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report["synthetic_only"])
            self.assertEqual(report["mismatched_observations"], 0)
            self.assertEqual(report["observation_count"], observations)
        self.assertEqual(self.run_cli("--version").stdout.strip(), "0.1.0")
        for args in (("--benchmark", "--iterations", "0"), ("--benchmark", "--iterations", "10001"), ()):
            self.assertEqual(self.run_cli(*args).returncode, 2)


if __name__ == "__main__":
    unittest.main()
