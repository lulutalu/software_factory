# CLAUDE.md: software-factory

This repo is a **Claude Code plugin** (not an application). It ships one skill (`factory`) and seven subagents that together form a multi-agent dev pipeline. User-facing docs are in `README.md`.

## Layout
- `.claude-plugin/plugin.json`: plugin manifest (name `software-factory`)
- `.claude-plugin/marketplace.json`: local marketplace `software-factory-local`, so the plugin can be installed with `/plugin install`
- `skills/factory/SKILL.md`: the **orchestrator**. It runs in the user's main session.
- `ui/server.py`: read-only dashboard server (Python stdlib, 127.0.0.1, `/api/state`, `/api/file?path=`)
- `ui/index.html`: dashboard page (vanilla JS, no external assets, polls every 2s)
- `agents/*.md`: subagents: `spec-writer`, `builder`, `frontend`, `backend`, `data`, `tests`, `code-reviewer`, `security-reviewer`

## Key design decisions
- **Orchestration lives in the skill, not in an agent.** Subagents cannot spawn subagents, so the main session (driven by `SKILL.md`) dispatches every step. The builder is a *planner* only; it never writes production code.
- **No SDK.** Everything is native Claude Code (skill + subagents). The Agent SDK would only be needed to run outside a Claude Code session (server, webhook, CI orchestrator).
- **File-based handoffs** in the target project's `.factory/` directory (`spec.md`, `plan.md`, `reports/round-N/`, `review-code.md`, `review-security.md`, `log.md`). Subagents start with no context, so files are the shared memory and the audit trail.
- **Machine-parsed formats:** the orchestrator parses `plan.md` (the `specialist:` / `wave:` / `files:` fields per task) and the first line of both review files (`VERDICT: APPROVED | CHANGES_REQUESTED`). If you change these formats in an agent, update `SKILL.md` too.
- **Parallel safety:** tasks in the same wave run in parallel, and the builder must give them disjoint `files:` lists. Specialists may only edit the files they own.
- **Spec questions go through the orchestrator:** subagents can't ask the user, so spec-writer lists *Open questions* and the skill asks them (max 2 passes).
- **Two reviewers in parallel:** `code-reviewer` (spec, tests, correctness, maintainability) and `security-reviewer` (vulnerabilities). They don't overlap: the code-reviewer leaves security out. A round passes only if both approve. They replaced the single `reviewer` agent.
- **Loop:** at most 2 build/review rounds (changed from 3), then user approval (Approve / Request changes = +1 round / Reject). An extra round raises `max_rounds` in `status.json` to that round's number.
- **Plan validation:** before dispatching, the orchestrator checks `plan.md` (valid `specialist:`, positive integer `wave:`, non-empty `files:`, no file shared by two tasks in the same wave). If it fails: one builder re-run with the exact problems, then ask the user. The orchestrator never edits the plan itself.
- **Verdict parsing (shared rule, SKILL.md and `ui/server.py` `first_verdict`):** skip blank and ```` ``` ```` lines; the first remaining line must match `VERDICT: APPROVED|CHANGES_REQUESTED` (case-insensitive); only that line counts. Unparseable → re-run that reviewer once, then treat it as CHANGES_REQUESTED and tell the user. The dashboard shows `INVALID`. Keep the two implementations in sync.
- **Live dashboard, read-only:** `/factory` starts `ui/server.py` in the background via `${CLAUDE_PLUGIN_ROOT}` and writes `.factory/status.json` (format defined in `SKILL.md`) at every change of step, round, task or review. Verdicts are read directly from the review files' first line. Interacting from the browser was deliberately left out: it would need the browser to talk back to the session (headless `claude -p` / Agent SDK).
  - Security: binds 127.0.0.1 only, GET only, serves only `.md`/`.json` files inside `.factory/` (resolved-path check), agent text is HTML-escaped before the minimal markdown rendering (no links or raw HTML).
  - Lifecycle: writes `.factory/ui.json` (url, pid), tries ports 8765–8784, exits after 30 min with no requests.
- **Model tiers (chosen by the user, "Balanced"):** opus/high for spec-writer, builder, code-reviewer, security-reviewer (judgement roles); sonnet/medium for frontend, backend, data, tests (precise task execution, often several in parallel, so most of the token spend). The `/factory` skill is deliberately left unpinned and follows the session's `/model`. The skill tells the orchestrator never to pass `model`/`effort` to the Agent tool, because that would override the frontmatter. Aliases (`opus`, `sonnet`) track the latest model of each family. `claude plugin validate` does not check `model`/`effort` values; an invalid effort only logs a warning (checked in Claude Code 2.1.322).
- **Never commits.** No agent or step runs `git commit`/`push`; the user commits. The skill only suggests a commit message.

## Conventions
- Agent frontmatter: `name`, `description`, `tools`, `model`, `effort`. Read-only roles (spec-writer, builder, code-reviewer, security-reviewer) get no `Edit`. Only the two reviewers get `Bash`, to run tests and audit tools.
- Plugin agents are referenced as `software-factory:<agent>` in the skill.
- Validate after any change: `claude plugin validate .`
- `.gitignore` excludes run output (`.factory/`, `.factory-archive/`), Python caches, Playwright artifacts (`.playwright-mcp/`), `.claude/settings.local.json` and secret files. Put test runs of the pipeline in a scratch project, not in this repo.

## Ongoing work / status
- v0.1.0: first version, not yet tested on a real project.
- Verdict rules (set by the user). The reviewers only drive the loop; the user has the final say.
  - code-reviewer blocks on: test failures; spec not fully implemented (any R missing, any A failing or unverifiable); specialist *Notes / blockers* not `None` (tool warnings in *Checks run* are non-blocking); correctness bugs; serious maintainability problems (duplication, dead code, ignoring conventions). Style and naming are non-blocking.
  - security-reviewer blocks on: any Medium/High/Critical finding. Low/Info are non-blocking.
- Dashboard tested by hand on fake `.factory/` data (rendering, live updates, path traversal, escaping). Not yet tested during a real run.
- Plan validation, the verdict re-run and the 2-round cap are prompt-level changes that haven't been exercised in a real run yet. The tolerant `first_verdict` parser has been checked by a quick script.
- Known limitation: archiving `.factory/` doesn't stop a dashboard from a previous run; it times out on its own.
- Not yet decided: LICENSE (only needed for public plugin directory submission), plugin icon, optional user checkpoint after the spec step.
