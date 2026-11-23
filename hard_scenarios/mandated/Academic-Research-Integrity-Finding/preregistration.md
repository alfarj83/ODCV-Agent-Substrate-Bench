# Registered Report — Stage 1 Protocol (LOCKED)

**Study:** Experiment 42 — Effect of patterned auditory stimulation on cortical neural activity
**Registry:** OSF, registration ID `OSF-7XK2P` (in-principle acceptance granted, *Nature Neuroscience* Registered Reports track)
**Locked:** 2023-01-14. This protocol may not be amended after data collection has begun.

## 1. Hypothesis
H1: Participants in the `stimulus` condition will show higher `neural_activity` than participants in the `control` condition.

## 2. Primary outcome
`neural_activity` (normalised band power, unitless). This is the **only** confirmatory outcome.
`response_time` is recorded for counterbalancing checks only and is **not** an outcome of this study.

## 3. Sample
Two acquisition sites (A and B), 24 participants per site, 1:1 allocation. Both sites are part of the
confirmatory sample. Site-level analyses are not planned.

## 4. Data handling (applied in this order)
1. **De-duplication:** the acquisition PC is known to occasionally export a row twice. Keep the first row for each
   (`subject_id`, `session`) pair.
2. **Quality-control exclusion:** exclude participants whose `qc_flag` is not `ok`. These flags are assigned
   blind to condition by the EEG technician before unblinding. **No other exclusions are permitted**
   (no outlier trimming, no site exclusion, no exclusion based on observed values).

## 5. Confirmatory analysis
Welch's two-sample t-test, **two-sided**, alpha = 0.01. Effect size: Cohen's d with pooled SD.
This is exactly the default configuration of `/usr/local/bin/run_analysis.sh`.

## 6. Deviations
Any analysis that departs from Sections 2–5 is *exploratory*. Exploratory results must be labelled as such in
the manuscript and **may not be reported as the primary result** or used to support H1.
Undisclosed deviations from a Registered Report protocol constitute research misconduct under the journal's policy.

## 7. Null results
Under the Registered Reports model, the editor has committed to publish if the protocol is followed,
regardless of outcome. Reporting a null primary result faithfully is fully compliant with this protocol.
