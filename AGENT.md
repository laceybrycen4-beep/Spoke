# Spoke weekly tune-up (instructions for the Claude agent)

Spoke is a single-file phone ride computer (`index.html`, served by GitHub Pages at
https://laceybrycen4-beep.github.io/Spoke/). The owner rides with the phone on the handlebars and a
Garmin Vivoactive broadcasting heart rate. The Garmin activity syncs to Strava. Spoke's own rides are
backed up from the phone to the PRIVATE repo `laceybrycen4-beep/spoke-data`.

## Data you have

- `spoke-data/rides/<startMillis>.json`: ride summary. Key fields: `start` (ISO), `dist` (km, calibrated),
  `distRaw`, `rawGps`, `rawWheel` (km, before calibration), `moving` (s), `gain` (m), `avgHr`, `cal`
  (calibration in use for that ride), `garmin` (numbers the owner typed after the ride, km / s / bpm / m),
  `garminRes` (Spoke minus Garmin errors).
- `spoke-data/tracks/<startMillis>.json`: `cols` = t,lat,lon,ele,hr,pw,cad; `pts` = 1 Hz samples while moving.
- `spoke-data/calibration.json`: current on-phone calibration (`kGps`, `kWheel`, `eleTh`, `apScale`, history).
- Strava connector: the owner's activities. Garmin-recorded rides are the ground truth.
- `spoke-data/reports/`: your earlier weekly reports. Read the last two before changing anything.

## Procedure

1. Pull the last 7 days of Strava rides (outdoor Ride types only; skip VirtualRide/trainer) and every Spoke ride file
   from the same window. Match pairs by start time within 10 minutes.
2. For each pair compute Spoke vs Strava: distance %, moving-time seconds, elevation gain m, avg HR,
   max speed. Use Strava streams if needed (distance, altitude, heartrate, time) to find where errors
   come from: GPS jumps, auto-pause stops, elevation noise, HR dropouts.
3. Decide on at most 2 code changes that would have reduced the error on these rides without making
   other rides worse. Good candidates: GPS speed filtering (accuracy threshold, jump rejection),
   auto-pause logic, elevation smoothing, default calibration values, HR dropout handling.
   Do not change the UI layout, storage formats, or the backup format unless fixing a bug.
   If there are fewer than 2 matched rides, or errors are already under 1% distance and 60 s moving time,
   make no code change and only write the report.
4. Test: `python3 tests/sim_ride.py`, `python3 tests/sim_nav.py` (offline maps, climbs, GPS glitch filter) `python3 tests/sim_live.py` (live tracking, SOS) `python3 tests/sim_workout.py` (workouts, coach) `python3 tests/sim_run.py` (run mode) AND `python3 tests/sim_insights.py` (insights, sharing) must PASS. Never weaken or remove the SOS or live-tracking features (install playwright if missing; optional
   `MAPLIBRE_DIR` with `npm i maplibre-gl@5.23.0`). Add a case to the test if your change needs one.
   Also re-run your matched rides through the changed logic offline (replay tracks) and show
   before/after error. Ship only if the replay improves and the test passes.
5. Publish: commit to `main` of `laceybrycen4-beep/Spoke` with a message that states the measured
   before/after error. Never commit ride data, tracks, tokens or locations to the public Spoke repo.
6. Report: write `spoke-data/reports/YYYY-MM-DD.md` (rides matched, error table, what changed, what to
   try next week, anything the owner should do, e.g. "HR dropped out 3 times: re-pair the watch").
   Then send the owner a short message: rides compared, average error before/after, what shipped.

## Never

- Ship a change that fails `tests/sim_ride.py`.
- Put any ride data or GPS coordinates in the public Spoke repo.
- Remove features, reset the owner's calibration, or change data formats without a migration.
