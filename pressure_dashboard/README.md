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

The app reads only the processed SQLite database and validation report. Re-run
the offline build after changing a source CSV or the workbook.

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

The sidebar applies format, season-range, and venue-country filters throughout.
Trend charts group matches by calendar year from the match date, so split
competition season labels such as `2022/23` do not appear as separate years.
The minimum sample default is 30 balls. Pressure-only narrows batter profiles to
batting-pressure deliveries and bowler profiles to bowling-pressure deliveries.
Overview, match-list, and venue chase cohorts use batting pressure. The
ordinary-versus-pressure comparison and chase-scenario heatmap retain both
states.

## Metric conventions

- Batting pressure uses the pre-ball state in innings 2: required run rate at
  least 15, no more than 30 known legal balls remaining, and at least three
  wickets lost.
- Bowling pressure uses the pre-ball chase state: exactly two wickets lost, no
  more than 30 known legal balls remaining, current scoring rate at least 11
  runs per over, and required run rate at least 9. Current scoring rate is
  calculated from the raw-field score proxy and known legal balls faced.
- A target uses matches.revised_target when present; otherwise it is first
  innings runs + extras_2_runs plus one.
- runs + extras_2_runs is shown as a raw-field proxy. It does not consistently
  reconcile with the match-result run margin, so those values are not presented
  as official scores.
- None, byes, and legbyes are treated as legal. wide and Overstep are treated
  as illegal. other, Penalty, blank, and any unrecognized labels have unknown
  legality. After such an event, later chase states are marked unknown rather
  than assuming the event used no legal ball.
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
