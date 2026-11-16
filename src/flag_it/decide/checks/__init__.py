"""Rule checks: every `code` check in the rules YAML, run against one snapshot.

    from flag_it.decide.checks.engine import run_rule_checks
    outcome = run_rule_checks(snapshot, rules, decision_id=..., deployment=load_deployment(),
                              calendar=load_calendar())
    outcome.flags, outcome.hard_failure

See engine.py for how results become flags, registry.py for which checks are implemented.
"""
