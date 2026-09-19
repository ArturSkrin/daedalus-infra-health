# design_rationale.md

## Where we started from

The agent has already decided. It read millions of events, filtered out the noise, opened or did not open an incident, saw or did not see a precursor. The screen is not there to help the engineer decide; it is there to show what was decided and give grounds to believe it. So we did not ask "which metrics are important", we asked "without which number would the engineer make a different decision". There turned out to be few such numbers.

The full breakdown of the 45-field catalog is in `metrics_catalog_triage.md`: 14 fields change the decision, 16 explain it, 6 change nothing. The five indicators are built from the first 14; the rest went into the drill-in or nowhere.

## Why these five

**Fleet state in one word.** People open a fitness tracker to see one word: ready, rest, train. Our screen works the same way: ALL CLEAR, SCHEDULE, ACT NOW. It is not a metric but a roll-up of the other four under priority rules, and it is what makes the "everything is fine" state reachable: it is defined as the absence of grounds for the other two decisions.

**Users now.** The only indicator from the present. It is RED turned into the share of traffic with errors, weighted by the service's place in the graph. It answers one thing only: are people suffering right now. p99 was left out on purpose, because the API has no latency baseline per service, and a threshold without a baseline is just a number.

**What's brewing.** The only indicator from the future and the most valuable in the set. The agent has two independent ways to see ahead: a match of an event chain against a known pattern (`precursorMatches`) and resource physics (PSI). Both are combined into one ring, because the engineer does not care why something is brewing, they care how much time there is. Trust in this indicator is built in: if the agent is right less often than it is wrong, the prediction dims and cannot give ACT NOW.

**Can we trust it.** The hackathon brief said it directly: zero events means either health or no data. The indicator first checks whether there is a stream from the cluster agent, then whether it is complete. Without it the "agent disconnected" scenario would look like the quietest morning of the year. Dark services lead to SCHEDULE, not to ALL CLEAR, because the API gives no way to tell a sleeping batch job from a dead one.

**How the day went.** The value on a quiet day. The engineer opens the tracker in the morning and after a release not to find trouble, but to see that there was none and what the agent did on its own. The indicator compares the last two hours with the previous twenty-two and reads how many incidents the agent closed without a human. It also catches the quiet regression that indicator 2 does not see, because the absolute impact is small while relative to the norm it is twice as bad.

## Why not others

**Not SNR and not event mix.** This is the most common mistake: showing how much noise was filtered out. The number is impressive, but none of the three decisions depends on it. It explains trust in the agent and lives in the drill-in of indicator 4.

**Not MTTR, MTTD, resolution rate.** These are agent quality goals, not fleet state. They can be 100% met at the moment when you need to run. The catalog adds one more argument: they live in core memory and reset on restart, so the ring can move with no change in the cluster.

**Not an error log counter.** A log spike with no impact on requests is an argument to do nothing. We checked this with scenario S06: none of the five indicators reads `signalsByType.log`, so 8.9 thousand error lines do not move the screen. If log errors became a sixth indicator, this scenario would break.

**Not a 0–100 score.** A composite score hides what exactly changed and contradicts itself: on the reference screen "100% of goals" sits next to the DEGRADED state and an open critical incident. The center of the screen should be taken by the decision.

**Not raw values.** errPct, PSI, p99, blastRadius exist in the formulas and in the drill-in. The screen shows "1.2% of requests degraded in 2 services", "2 more services will be hit", "memory is saturating". The engineer does not need to know that PSI exists.

## What the run revealed

The set was checked twice: on paper and on generated data through `mock_data/evaluate.py`. The paper run caught one thing (the floor of indicator 5). The data run caught three more that paper missed: wrong manual arithmetic of the error share, double counting of blast radius when summing graph neighbors, and a 6-hour window that blurred a two-hour regression. A later review of the code against incomplete input caught three more: an unknown indicator passed as green, absent resource-pressure data read as "no pressure", and readiness ignored when traffic data was stale. All nine fixes are listed at the end of `scenarios.md`. This is the argument for the method: an indicator set without scenarios is a wish list.

## Gaps in the catalog

Six are recorded in `metrics_catalog_triage.md`, and the runs added three. The three we submit for the separate nomination:

1. **No release event.** The brief says the tracker is opened after a release, but the API has no rollout marker. Indicator 5 is forced to answer "how the day went" instead of "how the release went".
2. **No USE history.** "Memory has been saturating for three days" from the brief cannot be computed: PSI exists only as a current snapshot.
3. **Security is invisible.** One of the three goals of the system has no field in the API at all, and the catalog admits this itself.

And one argument against the indicator that the organizers consider the main one: the **goal completion percentage** (awareness, warning, recovery) in the center of the reference screen. It measures the agent, not the fleet, and changes none of the three decisions.

## Watch and phone

On the phone all five indicators are visible without scrolling: the word in the center, four rings around it, the queue below them. On the watch three faces remain: four rings with the word, one open item with a "scheduled" button, and the time to the nearest failure from indicator 3. Confirming from the wrist is allowed only for SCHEDULE. ACT NOW requires the phone, because it requires context.
