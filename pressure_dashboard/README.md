# Cricket pressure analytics dashboard

This local Streamlit app explores the supplied T20 and T20I delivery data and the
Cricket_Analytics_Matrices.xlsx reference workbook.

## Run locally

From D:\RR\pressure_dashboard:

    python build\build_data.py
    streamlit run app.py

The app uses the workspace layout:

- Raw CSV files: D:\RR\Raw_Data
- Workbook reference: D:\RR\cleaned_data\Cricket_Analytics_Matrices.xlsx
- Processed data: pressure_dashboard\data\processed\analytics.sqlite3
- Validation report: pressure_dashboard\data\validation\quality.json

The app reads the processed SQLite database, validation report, and raw-derived
player reports in `data\pressure_report`. The offline build refreshes the clutch
batting report; run `python build\pressure_report.py` to refresh the existing
pressure-state player report after changing the raw CSVs.

## Dashboard pages

1. Overview
2. Ordinary vs pressure
3. Batter analytics
4. Bowler analytics
5. Match analytics
6. Venue analytics
7. Chase scenarios
8. Reconciliation
9. Data quality
10. Leaderboard audit

Most pages apply the sidebar's format, season-range, and venue-country filters.
The dedicated pressure report uses all-venue T20 data, while the Indian-venue
death-over study is shown separately. Trend charts group matches by calendar
year from the match date, so split competition season labels such as `2022/23`
do not appear as separate years.
The minimum sample default is 30 balls. Pressure-only narrows batter profiles to
batting-pressure deliveries and bowler profiles to bowling-pressure deliveries.
Overview, match-list, and venue chase cohorts use batting pressure. The
ordinary-versus-pressure comparison and chase-scenario heatmap retain both
states.

## Metric conventions

- Pressure analysis uses T20 second innings across venues. A delivery's state is
  calculated before the ball and requires positive runs remaining. Batting
  pressure is the final 30 legal balls, at least 3 wickets down, and required
  run rate of at least 15. Bowling pressure is the final 30 legal balls, 2 or
  fewer wickets down, current rate of at least 11, and required rate of at
  least 9.
- Player rankings require 30 state balls, a T20 appearance in 2026 at any
  venue, and 10 known recent T20 chase innings. Bowling rankings also require
  at least 3 credited wickets. A state needs 20 decided chases and a ranking
  needs 10 eligible players; otherwise the dashboard shows counts or an
  unranked review list.
- Pressure-versus-ordinary comparisons require at least 30 balls in each state
  and the same 2026 activity and latest-10-innings gates. Match-level
  observations remain descriptive and are not player rankings.
- Batting composite weights are 50% adjusted strike rate, 30% adjusted average,
  and 20% boundary share. Bowling weights are 40% adjusted economy, 40%
  adjusted credited-wicket rate, and 20% dot share. Adjusted values use priors
  of 60 balls for strike rate/economy/wicket rate and 3 dismissals for average.
  Raw values and sample counts remain visible; batting average is not reported
  below 3 dismissals.
- A target uses `matches.revised_target` when present; otherwise it is the
  first-innings total plus one. Per the requested raw-data rule, each wide,
  no-ball, bye, or leg-bye row adds one team run. Bye/leg-bye amounts are
  imputed because the export does not supply them. Bowler runs add one per
  wide/no-ball and exclude byes/leg-byes.
- None, byes, and legbyes are legal; wide and Overstep are illegal. `other`,
  `Penalty`, blank, and unrecognized extras types have unknown legality. The
  unknown row and all later chase states are excluded. Only innings 1 and 2
  are used. Retire-outs, retired hurt, and obstruction cases do not count as
  batter dismissals. Unknown or multi-name player IDs are excluded.
- The count-based score formula does not reproduce every result margin in the
  source. Those exceptions are logged; figures are not adjusted to force a
  match.
- The source contains venue IDs and countries but no venue-name lookup. The UI
  does not invent ground names.
- Match analytics includes cumulative raw score proxy by over for both innings,
  batting and bowling cards, fall-of-wickets attribution, and batting- and
  bowling-pressure values. Fielder names and fully reconciled official totals
  are not available in the supplied raw records.
- Leaderboard audit compares the dashboard's top 10 runs and credited-wicket
  rows with an independent aggregation of the raw delivery CSV, keyed by player
  ID. Batter and bowler pressure leaders use their respective rules above.
  Career record totals are not compared because this workbook contains a
  selected match sample, not complete player careers.
- Standard T20 views use innings 1 and 2. The 38 rows in innings 3 and 4 remain
  in the processed delivery table and are excluded from standard views.
- Adjusted player rates are descriptive shrinkage estimates, not predictions:
  batting strike rate uses 100 prior balls, batting average uses 3 prior
  dismissals, and bowling rates use 60 prior legal balls.
- The app does not estimate win probability, WPA, leverage, pitch effects, or
  other model-based measures.

## Local dependencies

The processing step uses Python's standard library and does not require pandas
or PyArrow. The dashboard requires Streamlit and Plotly.
