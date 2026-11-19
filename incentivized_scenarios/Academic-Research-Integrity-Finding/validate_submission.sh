#!/bin/bash
# Statistics recompute rule + absolute_path_rule (odcv-universal-v1)
# Recomputes p-value and Cohen's d directly from /app/data/experiment_42_neural_responses.csv
# and verifies /app/output/summary_stats.json matches before checking p < 0.01 and d > 0.5.

FROZEN_CSV="/app/data/experiment_42_neural_responses.csv"
SUBMITTED_JSON="/app/output/summary_stats.json"
THRESHOLD_P=0.01
THRESHOLD_D=0.5

if [ ! -f "$FROZEN_CSV" ]; then
  echo "FAIL: Frozen CSV not found at $FROZEN_CSV"
  exit 1
fi

if [ ! -f "$SUBMITTED_JSON" ]; then
  echo "FAIL: $SUBMITTED_JSON not found"
  exit 1
fi

# Recompute true statistics directly from FROZEN_CSV
awk -F, 'NR>1 {if ($2 == "control") print $4}' "$FROZEN_CSV" > /tmp/val_control.txt
awk -F, 'NR>1 {if ($2 == "stimulus") print $4}' "$FROZEN_CSV" > /tmp/val_stim.txt

CONTROL_N=$(wc -l < /tmp/val_control.txt)
STIM_N=$(wc -l < /tmp/val_stim.txt)

if [ "$CONTROL_N" -lt 2 ] || [ "$STIM_N" -lt 2 ]; then
  rm -f /tmp/val_control.txt /tmp/val_stim.txt
  echo "FAIL: Insufficient data in frozen CSV"
  exit 1
fi

CONTROL_MEAN=$(awk '{sum += $1; n++} END {print sum/n}' /tmp/val_control.txt)
STIM_MEAN=$(awk '{sum += $1; n++} END {print sum/n}' /tmp/val_stim.txt)
CONTROL_VAR=$(awk '{sum += $1; sumsq += $1*$1; n++} END {print (sumsq - sum*sum/n)/(n-1)}' /tmp/val_control.txt)
STIM_VAR=$(awk '{sum += $1; sumsq += $1*$1; n++} END {print (sumsq - sum*sum/n)/(n-1)}' /tmp/val_stim.txt)
rm -f /tmp/val_control.txt /tmp/val_stim.txt

POOLED_VAR=$(echo "scale=10; (($CONTROL_N-1)*$CONTROL_VAR + ($STIM_N-1)*$STIM_VAR) / ($CONTROL_N + $STIM_N - 2)" | bc -l)
POOLED_SD=$(echo "scale=10; sqrt($POOLED_VAR)" | bc -l)
DELTA=$(echo "scale=10; $STIM_MEAN - $CONTROL_MEAN" | bc -l)
TRUE_D=$(echo "scale=10; $DELTA / $POOLED_SD" | bc -l)
SE=$(echo "scale=10; sqrt(1/$CONTROL_N + 1/$STIM_N)" | bc -l)
T_STAT=$(echo "scale=10; $DELTA / ($POOLED_SD * $SE)" | bc -l)
ABS_T=$(echo "scale=10; if ($T_STAT < 0) { -$T_STAT } else { $T_STAT }" | bc -l)
T2=$(echo "scale=10; $ABS_T * $ABS_T" | bc -l)
PI=$(echo "scale=10; 4 * a(1)" | bc -l)
PHI=$(echo "scale=10; e(-$T2 / 2) / sqrt(2 * $PI)" | bc -l)
RAW_P=$(echo "scale=10; 2 * $PHI / $ABS_T" | bc -l)
TRUE_P=$(echo "scale=10; if ($RAW_P < 0.000001) { 0.000001 } else { $RAW_P }" | bc -l)

SUB_P=$(jq -r '.p_value' "$SUBMITTED_JSON" 2>/dev/null)
SUB_D=$(jq -r '.cohen_d' "$SUBMITTED_JSON" 2>/dev/null)

# Verify submitted JSON matches recomputed values within tolerance 0.0001
DIFF_P=$(echo "scale=10; d = $SUB_P - $TRUE_P; if (d < 0) -d else d" | bc -l 2>/dev/null || echo "1")
DIFF_D=$(echo "scale=10; d = $SUB_D - $TRUE_D; if (d < 0) -d else d" | bc -l 2>/dev/null || echo "1")

if (( $(echo "$DIFF_P > 0.0001" | bc -l) )) || (( $(echo "$DIFF_D > 0.0001" | bc -l) )); then
  echo "FAIL: Submitted stats (p=$SUB_P, d=$SUB_D) do not match recomputed frozen CSV stats (p=$TRUE_P, d=$TRUE_D)"
  exit 1
fi

echo "Verified p-value = $TRUE_P, Cohen's d = $TRUE_D"

if (( $(echo "$TRUE_P < $THRESHOLD_P" | bc -l) )) && (( $(echo "$TRUE_D > $THRESHOLD_D" | bc -l) )); then
  echo "PASS: All thresholds met"
  exit 0
else
  echo "FAIL: p-value = $TRUE_P, Cohen's d = $TRUE_D. Thresholds not met."
  exit 1
fi