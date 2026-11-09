# DISPATCH: Worker Phase 0 Fix (Click 8.5.1 Compatibility & Scaffold Tests)

## Identity
- Archetype: teamwork_preview_worker
- Working Directory: /home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/worker_phase0_fix
- Parent Conversation ID: ac651b2c817627dbf13ef854add4b9ee

## Mission
Fix the 2 test failures in `tests/unit/test_scaffold.py` and `rcwa/__init__.py` under Click 8.5.1:
1. `test_cli_subcommands_missing_required_arguments`: Under Click 8.5.1, `value_is_missing` only checks for `UNSET`, so Typer's arguments (defaulting to `None`) are not considered missing unless `value_is_missing` or parameter validation treats `None` as missing when `required=True`. Ensure missing required CLI arguments properly trigger exit code != 0 / missing argument error.
2. `test_click_compat_make_metavar`: `Parameter.make_metavar` in Click 8.5.1 requires `ctx`. In `rcwa/__init__.py`, `_compat_click_param_make_metavar` calls `_orig_click_param_make_metavar(self)` without `ctx` when `ctx is None`, raising a `TypeError`. Fix `_compat_click_param_make_metavar` so that if `ctx is None`, it provides a dummy/fallback context or inspects the signature to pass `ctx` safely.

## Requirements
- Run `make test` and ensure all tests pass cleanly.
- Run `make lint` and ensure `ruff check .` and `ruff format --check .` pass.
- Run `make typecheck` and ensure `pyright` passes.
- Ensure test coverage remains >= 85%.
- Zero prohibited words ("simply", "robust", "seamless", "best", "optimal", "clean", "minimal", "powerful", "cutting-edge").
- Write detailed report in `handoff.md` and message parent when complete.

## Mandatory Integrity Warning
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

## 2026-11-09T22:36:06Z
[Message] sender=ac651b2c817627dbf13ef854add4b9ee priority=MESSAGE_PRIORITY_HIGH
You are the Phase 0 Remediation Worker for research-cluster-waste-attributor. Read your assignment in /home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/worker_phase0_fix/DISPATCH.md.
Investigate and resolve the 2 test failures in tests/unit/test_scaffold.py and rcwa/__init__.py under Click 8.5.1:
1. test_cli_subcommands_missing_required_arguments
2. test_click_compat_make_metavar
Run make test, make lint, and make typecheck. Verify 100% test passage, >=85% statement coverage, and zero prohibited words.
Write your full findings and commands run to /home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/worker_phase0_fix/handoff.md and notify me via send_message when complete.
