# Spoke

Phone ride computer for the handlebars: GPS speed and distance, Bluetooth heart rate (Garmin
Vivoactive broadcast), power and speed/cadence sensors, a street map with GPX/TCX route import and
turn cues, laps, touch lock, and sunlight mode.

Open: https://laceybrycen4-beep.github.io/Spoke/ (iPhone: use the Bluefy browser for Bluetooth).

- After each ride, **Confirm with Garmin** tunes distance, climbing and auto-pause to match your watch.
- Rides back up to a private GitHub repo (`spoke-data`) set in Settings, Backup.
- A weekly Claude agent compares Spoke with Strava/Garmin and ships tested fixes: see `AGENT.md`.
- Live tracking: friends open the shared `live.html` link (end-to-end encrypted, relayed by ntfy.sh). SOS: hold the red button 2 s.
- Tests: `python3 tests/sim_ride.py`, `python3 tests/sim_nav.py`, `python3 tests/sim_live.py`, `python3 tests/sim_workout.py`
- Workouts tab: 13 preloaded workouts and a rule-based coach that picks one from your time, feel, goal and last 7 days of rides.
