# software-factory

A Claude Code plugin that runs a multi-agent development pipeline from a single command:

```
/factory <request>
      │
      ▼
 spec-writer ──(open questions? ask user)──► .factory/spec.md
      │
      ▼
 ┌──► builder (planner) ─────────────────► .factory/plan.md   (tasks, waves, file ownership)
 │        │
 │        ▼
 │   specialists, wave by wave (parallel inside a wave)
 │   frontend · backend · data · tests ──► code + .factory/reports/round-N/
 │        │
 │        ▼
 │   code-reviewer ‖ security-reviewer ──► .factory/review-code.md
 │        │      (in parallel)               .factory/review-security.md
 │        │
 └─ either says CHANGES_REQUESTED (max 2 rounds)
          │ both APPROVED (or 2 rounds used)
          ▼
   user approval: Approve · Request changes · Reject
```

Nothing is ever committed. You review the result and commit it yourself.

Safety checks built into the loop:
- **Plan check:** before any specialist runs, the orchestrator checks `plan.md` (valid specialist, wave and files on every task; no file shared by two tasks in the same wave). If the check fails, the builder gets one retry, then you're asked.
- **Verdict check:** a review whose verdict line can't be read gets one re-run. If it's still unreadable, it counts as CHANGES_REQUESTED and you're told. The dashboard shows it as `INVALID`.
- **Extra rounds:** "Request changes" at the end adds a round beyond the cap (the dashboard shows e.g. `Round 3 / 3`).

## Live dashboard

When a run starts, `/factory` launches a small local web page and prints its URL (by default `http://127.0.0.1:8765/`; the next free port is used if that one is busy). The page updates every 2 seconds and shows:
- the current step and round,
- the waves of tasks and each specialist's status,
- both review verdicts with blocking / non-blocking counts,
- every file in `.factory/` (spec, plan, reports, reviews, log), rendered.

**Answering from the browser:** when the spec-writer has open questions, or at the final approval, a "Your input is needed" panel appears at the top of the page (and the tab title shows ●). You can answer there **or** in the terminal: the first answer wins. Everything else on the page is read-only.

It needs only `python3` (standard library), listens on `127.0.0.1` only (answers need a random per-page token, a same-origin request and the right Host header, so other websites can't answer for you), and stops by itself after 30 minutes without visitors. To stop it earlier, run `kill <pid>` (the PID is in `.factory/ui.json`).

To open the dashboard on a past run by hand:
```bash
python3 /home/lulu/projects/software_factory/ui/server.py --factory-dir /path/to/project/.factory
```

## Install

**Try it for one session (no install):**
```bash
claude --plugin-dir /home/lulu/projects/software_factory
```

**Install it for every project** (inside Claude Code):
```
/plugin marketplace add /home/lulu/projects/software_factory
/plugin install software-factory@software-factory-local
```
Restart Claude Code after installing. After you edit the plugin, run `/plugin update software-factory@software-factory-local` (or `claude plugin update …`) and restart again.

## Usage

From any project directory:
```
/software-factory:factory add a /health endpoint that returns uptime and version
```
(Plugin skills are namespaced. If no other skill is called `factory`, `/factory` also works.)

The pipeline creates a `.factory/` folder in the target project with all handoff files. Add it to that project's `.gitignore` if you don't want it tracked.

## Agents

| Agent | Role | Can edit code? | Model / effort |
|---|---|---|---|
| `spec-writer` | Turns the request into requirements (R…) and acceptance criteria (A…), and lists open questions | No (writes `spec.md` only) | opus / high |
| `builder` | Architect/planner: splits the spec into tasks assigned to specialists, in waves, with per-file ownership | No (writes `plan.md` only) | opus / high |
| `frontend` | UI, components, styling | Yes, only the files it owns | sonnet / medium |
| `backend` | Server/API/CLI logic | Yes, only the files it owns | sonnet / medium |
| `data` | Schemas, migrations, queries | Yes, only the files it owns | sonnet / medium |
| `tests` | Tests for acceptance criteria; runs the suite | Yes, test files only | sonnet / medium |
| `code-reviewer` | Spec coverage, runs tests, correctness and maintainability review | No (writes `review-code.md` only) | opus / high |
| `security-reviewer` | Vulnerability audit with severity ratings, dependency audit | No (writes `review-security.md` only) | opus / high |

Opus is used for the roles that make judgements (spec, plan, reviews) and Sonnet for the specialists, which follow precise task instructions and often run several at once. The `/factory` orchestrator itself is not pinned: it uses your session's `/model` and effort.

## Customising

- **Add a specialist:** create `agents/<name>.md` (copy an existing specialist), then add it to the specialist table in `agents/builder.md` and the agent table in `skills/factory/SKILL.md`.
- **Change an agent's model or effort:** edit `model:` (`opus`, `sonnet`, `haiku`, `inherit` or a full model ID) and `effort:` (`low`, `medium`, `high`, `xhigh`, `max`) in its frontmatter in `agents/<name>.md`. `claude plugin validate` doesn't check these values, so double-check spelling.
- **Change the loop cap:** edit "max 2 rounds" in `skills/factory/SKILL.md` (Step 2 heading, the `round = …` loop, the `round < 2` / `round = 2` rules, the frontmatter description and `max_rounds` in the `status.json` example).
- **Change the dashboard:** `ui/index.html` (page), `ui/server.py` (API) and `ui/wait_answer.py` (answer watcher). The page reads `.factory/status.json` and `.factory/inbox/pending.json`; both formats are defined in `skills/factory/SKILL.md`.
- **Change what blocks a review:** edit the verdict rules in `agents/code-reviewer.md` and `agents/security-reviewer.md`. A round passes only if **both** approve. Currently blocking:
  - *code-reviewer*: test failures, spec not fully implemented, specialist notes/blockers (tool warnings like lint are reported but don't block), correctness bugs, serious maintainability problems.
  - *security-reviewer*: any Medium, High or Critical finding (Low/Info are reported only).

  The reviewers only decide whether another round runs; you still make the final call.
