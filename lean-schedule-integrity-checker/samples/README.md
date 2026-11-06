# Sample project: Harbourside Health Centre

A fictional three-storey health centre, 89 activities, data date 2 March 2026. The same
project is provided in every input format so you can compare them:

| File | Contents |
|---|---|
| `harbourside-health-centre.xer` | Primavera P6 export (activity codes `Trade` and `Zone`, resources, a 7-day curing calendar, UK holidays) |
| `harbourside-health-centre.xml` | Microsoft Project XML (custom fields `Trade`, `Zone` and `Activity ID`, a deadline on project completion) |
| `harbourside-health-centre.csv` | CSV schedule with comment lines for the data date, deadline and holidays |
| `weekly-work-plans.csv` | Eight weeks of Last Planner weekly commitments with reasons for non-completion |
| `constraint-log.csv` | Twenty make-ready constraints, some removed, some open, some overdue |

The history is simulated by [generate_samples.py](./generate_samples.py?WT.mc_id=academic-105485-koreyst):
a baseline is calculated from the start date, an "as-built" run with overruns gives the actual
dates, and the remaining work is rescheduled from the data date. Problems are planted on
purpose so every check has something to find, for example:

- open ends (landscaping, signage, the gas connection) and two leads in the fit-out,
- a 25-day lag standing in for facade fabrication and a mandatory start on a delivery,
- a start-to-finish link and a lift installation with only a finish-to-finish predecessor,
- a deadline that the forecast misses, which gives negative float on the critical path,
- stale forecast dates and an actual start after the data date (XER only),
- out-of-sequence drylining, stalled MEP risers and trades stacked in the same zones,
- a takt area of six zones where one zone (L2-B) holds 80% more work than a standard zone.

Regenerate the files after changing the generator:

```bash
python samples/generate_samples.py
```
