# Checks reference

Every check, what it measures and the default threshold. Thresholds can be changed with
`--set key=value` (see [settings.py](../lean_sic/settings.py?WT.mc_id=academic-105485-koreyst)).

**Populations.** Unless stated otherwise, checks look at *incomplete* tasks and milestones.
Level-of-effort (hammock) and WBS summary activities are left out, as in most DCMA tools.
Relationship checks look at links whose successor is not finished.

**Scoring.** A check scores 1 when it meets its threshold. Otherwise it loses credit in
proportion to the miss, reaching 0 when the miss is twice the threshold (at least 10 points)
past it. Index checks (CPLI, BEI) score 0 at 0.75. The group score is the weighted average of
its checks on a 0-100 scale. Grades: A at 90 or more, B at 80, C at 70, D at 60, F below 60.
Info checks are not scored.

## DCMA 14-Point Assessment

| ID | Check | Default threshold | Weight | Lean waste |
|---|---|---|---|---|
| DCMA-01 | Missing logic: no predecessor and/or successor (project start and finish exempt) | at most 5% | 10 | Defects |
| DCMA-02 | Leads (negative lag) | 0% | 5 | Defects, Muri |
| DCMA-03 | Lags | at most 5% of links | 4 | Waiting |
| DCMA-04 | Finish-to-start share of links | at least 90% | 3 | - |
| DCMA-05 | Hard constraints (start/finish on, on or before, mandatory) | at most 5% | 7 | Overproduction, Mura |
| DCMA-06 | High float, above 44 working days | at most 5% | 5 | Inventory, Overproduction |
| DCMA-07 | Negative float | 0% | 8 | Muri, Waiting |
| DCMA-08 | High duration, original duration above 44 working days | at most 5% | 5 | Inventory, Mura |
| DCMA-09 | Invalid dates: actuals after the data date, forecasts before it | 0% | 8 | Defects |
| DCMA-10 | Tasks without resources (informational when the schedule has no resources) | 0% | 2 | Muri |
| DCMA-11 | Missed tasks: baselined to finish by the data date, finished late or not finished | at most 5% | 6 | Waiting, Mura |
| DCMA-12 | Critical path test: a 600-day delay on the lowest-float path must move the finish by 600 days (5 activities sampled) | pass | 8 | Defects |
| DCMA-13 | Critical path length index, (CPL + project float) / CPL | at least 0.95 | 6 | Muri |
| DCMA-14 | Baseline execution index, completed / baselined to finish by the data date | at least 0.95 | 6 | Mura, Waiting |

## Beyond DCMA

| ID | Check | Default threshold | Weight | Lean waste |
|---|---|---|---|---|
| EXT-01 | Dangling activities: start not driven (only FF/SF predecessors) or finish drives nothing (only SS successors) | 0% | 6 | Defects |
| EXT-02 | Out-of-sequence progress: started before a finish-to-start predecessor finished | at most 5% of started work | 4 | Defects, Motion |
| EXT-03 | Circular logic (loops) | none | 8 | Defects |
| EXT-04 | Redundant finish-to-start links already implied by a longer chain | at most 5% | 2 | Extra-processing |
| EXT-05 | Long lags, above 10 working days | at most 1% | 3 | Waiting |
| EXT-06 | Start-to-finish links | 0% | 2 | Defects |
| EXT-07 | Level-of-effort or summary activities driving real work | none | 2 | Defects |
| EXT-08 | Critical path density: share of incomplete work that is critical | at most 25% | 3 | Muri |
| EXT-09 | Driving path continuity: the longest path must start at the data date, not at a date constraint | continuous | 5 | Defects |
| EXT-10 | Logic density: links per activity (predecessors + successors) | 2.0 to 6.0 | 3 | Defects, Extra-processing |
| EXT-11 | Status and data integrity: missing actuals, finish before start, zero-duration tasks, milestones with duration, duplicate IDs | 0% | 4 | Defects |
| EXT-12 | Soft constraints (start/finish on or after, as late as possible) | info | - | Overproduction |
| EXT-13 | Stored float against float recalculated by the built-in CPM engine | info | - | - |
| EXT-14 | Merge hotspots: 6 or more predecessors | info | - | Waiting |

## Lean readiness

| ID | Check | Default threshold | Weight | Lean waste |
|---|---|---|---|---|
| LEAN-01 | Lookahead granularity: lookahead tasks with more than 10 working days remaining | at most 15% | 8 | Inventory, Mura |
| LEAN-02 | Who: lookahead tasks with a responsible trade | at least 95% | 7 | Non-utilised talent |
| LEAN-03 | Where: incomplete tasks with a location or zone | at least 80% | 6 | Motion, Transportation |
| LEAN-04 | Push constraints: lookahead activities held to a date constraint | at most 5% | 5 | Overproduction |
| LEAN-05 | Slow or stalled work in progress: running 10+ days at under half the planned rate | at most 10% of work in progress | 5 | Inventory, Waiting |
| LEAN-06 | Trade flow continuity: idle gaps over 5 working days between a trade's work periods | at most 20% of re-entries | 6 | Waiting, Transportation, Non-utilised talent |
| LEAN-07 | Trade stacking: zone-days with two or more trades | at most 15% | 6 | Motion, Muri, Defects |
| LEAN-08 | Takt balance: average coefficient of variation of each trade's work per zone | at most 0.35 | 5 | Mura, Waiting |
| LEAN-09 | Make-ready: activities starting in the next 2 weeks that still have open constraints (needs a constraint log) | at most 10% | 7 | Waiting |
| LEAN-10 | Plan reliability: Percent Plan Complete over the last 4 weeks (needs weekly work plans) | at least 80% | 8 | Mura, Waiting |
| LEAN-11 | Overdue constraints: open constraints past their need-by date (needs a constraint log) | at most 10% | 5 | Waiting |

## Lookahead window

The lookahead holds incomplete work that is already under way or starts within
`lookahead_weeks` (default 6) of the data date. The make-ready window (`make_ready_weeks`,
default 2) is the part that should already be free of constraints.

## Float

Total float is read from the file when at least 90% of incomplete activities have it (P6 and
Microsoft Project store it). Otherwise it is recalculated by the built-in CPM engine, which
schedules from the data date with retained logic, honours lags, leads, constraints, deadlines
and a project "must finish by" date, and breaks loops so the calculation always completes.
