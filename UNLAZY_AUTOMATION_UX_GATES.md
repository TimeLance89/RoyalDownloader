# .unlazy acceptance gates – Automation schedule UX

- G1 CHECK: Weekday schedule exposes Jederzeit / Nur nachts / Eigene Zeiten and hides raw numeric hour controls.
- G2 CHECK: Weekend schedule exposes Jederzeit / Wie Mo–Fr / Eigene Zeiten.
- G3 CHECK: Custom schedule and movie-upgrade windows use HH:MM time inputs while persisting the existing hour-based backend contract.
- G4 CHECK: Existing saved policies round-trip into the correct friendly mode without changing scheduling semantics.
- G5 CHECK: Responsive/focus/reduced-motion contracts remain covered.
- G6 CHECK: Full repository verify workflow succeeds on the exact final head before merge to overnight.
