---
name: factory
description: Run the software-factory pipeline on a feature request — spec-writer → builder (planner) → domain specialists → code-reviewer + security-reviewer (in parallel), looping back to the builder on failed reviews (max 2 rounds), then asking the user for final approval.
argument-hint: <feature request>
disable-model-invocation: true
---

# Software factory orchestrator

You are the **orchestrator**. You run the pipeline below in order. You never write production code yourself: all the work is done by the subagents. Your job is to dispatch them, pass the right inputs, read their outputs, and talk to the user.

**Request:** $ARGUMENTS

If the request is empty, ask the user what they want built and stop until they answer.

## Agents
| Step | Subagent type |
|---|---|
| Spec | `software-factory:spec-writer` |
| Plan | `software-factory:builder` |
| Build | `software-factory:frontend`, `software-factory:backend`, `software-factory:data`, `software-factory:tests` |
| Review | `software-factory:code-reviewer`, `software-factory:security-reviewer` (in parallel) |

Subagents start with no context. Every prompt you send must include everything they need: the request, the round number, the task text and the file paths to read.

Each agent's model and reasoning effort are set in its own frontmatter (`model:` / `effort:` in `agents/*.md`). **Never pass `model` or `effort` to the Agent tool** when you launch them: that would override the agent's setting for that call.

## Working directory: `.factory/`
All handoffs go through files in the target project:
- `.factory/spec.md`: written by spec-writer
- `.factory/plan.md`: written by builder (overwritten each round)
- `.factory/reports/round-N/<task-id>.md`: specialist reports, saved by **you**
- `.factory/review-code.md`: written by code-reviewer (overwritten each round)
- `.factory/review-security.md`: written by security-reviewer (overwritten each round)
- `.factory/log.md`: a one-line-per-step log you append to (timestamp, step, outcome)
- `.factory/status.json`: live state for the dashboard, written by **you** (see *Dashboard* below)
- `.factory/ui.json`: dashboard URL and PID, written by the dashboard server

**Before starting:** if `.factory/` already exists, ask the user whether to **archive** it (move it to `.factory-archive/<timestamp>/`) or **stop**. Never delete it silently. If the project is a git repo and `.factory/` is not ignored, tell the user they may want to add it to `.gitignore`. Do not edit `.gitignore` yourself.

## Dashboard (live web UI)
Right after the *Before starting* check, start the read-only dashboard **in the background** (use `run_in_background`):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/ui/server.py" --factory-dir "$PWD/.factory"
```

It prints `FACTORY_UI <url>` and writes the URL to `.factory/ui.json`. Give the user the URL in one line. If the server fails to start (no `python3`, etc.), tell the user and carry on without it: the dashboard is optional.

**Keep `.factory/status.json` up to date.** Overwrite it every time the step, the round, a task status or a review status changes. Always write the whole file:

```json
{
  "request": "<the request>",
  "step": "setup | spec | questions | plan | build | review | approval | done",
  "round": 1,
  "max_rounds": 2,
  "waves": [
    { "wave": 1, "tasks": [
      { "id": "T1", "title": "…", "specialist": "backend", "status": "pending | running | done | blocked" }
    ] }
  ],
  "reviews": { "code": "pending | running | done", "security": "pending | running | done" },
  "outcome": null,
  "updated_at": "<ISO-8601 timestamp>"
}
```

- `round` is `null` before the first plan. On a new round, reset `waves` from the new plan and set both `reviews` back to `pending`.
- `max_rounds` starts at 2. When the user asks for an extra round in Step 3, raise it to that round's number, so the dashboard never shows a round above the max (e.g. `3 / 3`, not `3 / 2`).
- `outcome` becomes `approved`, `rejected` or `review_failed` at the end (Step 3).
- The dashboard reads the verdicts directly from the review files, so `reviews` only needs to say whether each review is running.

## Step 1: Spec
1. Launch `spec-writer` with the request.
2. Read `.factory/spec.md`. If *Open questions* is not `None`, ask the user those questions (use AskUserQuestion; group them, max 4 per call), then re-run `spec-writer` with the request **and** the answers. Allow at most 2 question passes; after that, carry any remaining open questions into the final approval summary.

## Step 2: Build/review loop (max 2 rounds)
For `round = 1, 2`:

1. **Plan**: launch `builder` with the round number. From round 2 on, tell it to read `.factory/review-code.md` and `.factory/review-security.md` (and any user feedback) and plan **only the fixes for the blocking findings**.
2. **Validate the plan**: read `.factory/plan.md` and check every task before dispatching anything:
   - it has a `specialist:` that is one of `frontend`, `backend`, `data`, `tests`;
   - it has a `wave:` that is a positive integer and a non-empty `files:` list;
   - no file appears in the `files:` of two tasks **in the same wave** (compare paths after trimming spaces and a leading `./`).

   If anything fails, re-run `builder` **once** with the round number and the exact list of problems (e.g. "wave 1: `src/api.ts` is in T1 and T3"), then validate again. If the plan is still invalid, stop and show the problems to the user (AskUserQuestion: re-run the builder again with their guidance, or stop the run). Never fix the plan yourself.
3. **Dispatch**: group the tasks by `wave`. For each wave, in ascending order:
   - Launch every task of the wave **in parallel**, as one message with several Agent calls. Use the subagent type `software-factory:<specialist>` and pass the full task block verbatim, plus "read `.factory/spec.md` for context".
   - Wait for the whole wave to finish before starting the next one.
   - Save each final report to `.factory/reports/round-<N>/<task-id>.md`.
   - If a specialist reports a blocker (for example it needed a file it didn't own), note it for the reviewers. Don't fix it yourself.
4. **Review**: launch `code-reviewer` and `security-reviewer` **in parallel** (one message, two Agent calls), each with the round number and the list of report files. Wait for both, then read the verdict of `.factory/review-code.md` and `.factory/review-security.md`.
   - **Reading a verdict:** skip blank lines and lines starting with ```` ``` ````. The first remaining line must be `VERDICT: APPROVED` or `VERDICT: CHANGES_REQUESTED` (ignore case and extra spaces). Look only at that line, never further down the file.
   - **Unparseable verdict** (missing file, or that line doesn't match): re-run **only that reviewer** once, reminding it that line 1 must be the bare verdict line. If it's still unparseable, count it as `CHANGES_REQUESTED` and flag it to the user ("security review verdict unreadable, treated as CHANGES_REQUESTED").
   - **Both** `APPROVED` → go to Step 3.
   - Either one `CHANGES_REQUESTED` and round < 2 → next round.
   - Either one `CHANGES_REQUESTED` and round = 2 → stop looping and go to Step 3, clearly flagging which review did **not** pass.

Tell the user about progress in one short line per step (e.g. "Round 2 · wave 1: backend T1, data T2 running…").

## Step 3: User approval
Show the user a summary:
- What was built (from the spec's Goal), and the number of rounds used.
- Files created/modified (use `git status` if it's a repo, otherwise use the specialists' reports).
- Both review verdicts, acceptance criteria results, test results, the security findings with their severity, and **all** NON-BLOCKING findings from both reviews.
- Any unresolved open questions or blockers.

Then ask (AskUserQuestion):
- **Approve**: the work is accepted. Suggest a commit message, but **do not commit**: the user commits.
- **Request changes**: collect their feedback and run **one more** round of Step 2 (round = previous round + 1) with the feedback passed to the builder as blocking findings. In `status.json`, set `max_rounds` to that new round number if it's higher. Ask for approval again afterwards.
- **Reject**: stop. Leave the files as they are and remind the user they can discard the changes (e.g. `git restore` / `git clean`) themselves.

When the run ends, set `step` to `done` and fill in `outcome` in `status.json`. Leave the dashboard running so the user can browse the results; it stops by itself after 30 minutes without visitors. Tell the user they can stop it sooner with `kill <pid>` (the PID is in `.factory/ui.json`).

## Hard rules
- Never run `git commit`, `git push`, or any command that creates commits or rewrites history.
- Never read secrets (`.env*`, keys, credentials). If a task needs one, stop and ask the user.
- Never skip either reviewer or the user approval step.
