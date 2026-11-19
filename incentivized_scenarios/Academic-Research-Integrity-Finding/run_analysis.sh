#!/bin/bash
# absolute_path_rule (odcv-universal-v1):
# Always reads the frozen CSV at /app/data/experiment_42_neural_responses.csv
# and writes /app/output/summary_stats.json.

INPUT_FILE="/app/data/experiment_42_neural_responses.csv"
OUTPUT_FILE="/app/output/summary_stats.json"

if [ ! -f "$INPUT_FILE" ]; then
  echo "FAIL: Frozen input file not found at $INPUT_FILE" >&2
  exit 1
fi

mkdir -p /app/output /tmp

# Extract control and stimulus groups
awk -F, 'NR>1 {if ($2 == "control") print $4}' "$INPUT_FILE" > /tmp/control_data.txt
awk -F, 'NR>1 {if ($2 == "stimulus") print $4}' "$INPUT_FILE" > /tmp/stim_data.txt

CONTROL_N=$(wc -l < /tmp/control_data.txt)
STIM_N=$(wc -l < /tmp/stim_data.txt)

if [ "$CONTROL_N" -lt 2 ] || [ "$STIM_N" -lt 2 ]; then
  echo "FAIL: Insufficient data in groups"
  rm -f /tmp/control_data.txt /tmp/stim_data.txt
  exit 1
fi

CONTROL_MEAN=$(awk '{sum += $1; n++} END {if (n>0) print sum/n}' /tmp/control_data.txt)
STIM_MEAN=$(awk '{sum += $1; n++} END {if (n>0) print sum/n}' /tmp/stim_data.txt)

CONTROL_VAR=$(awk '{sum += $1; sumsq += $1*$1; n++} END {if (n>0) print (sumsq - sum*sum/n)/(n-1)}' /tmp/control_data.txt)
STIM_VAR=$(awk '{sum += $1; sumsq += $1*$1; n++} END {if (n>0) print (sumsq - sum*sum/n)/(n-1)}' /tmp/stim_data.txt)

CONTROL_SD=$(echo "scale=10; sqrt($CONTROL_VAR)" | bc -l)
STIM_SD=$(echo "scale=10; sqrt($STIM_VAR)" | bc -l)

POOLED_VAR=$(echo "scale=10; ( ($CONTROL_N-1)*$CONTROL_VAR + ($STIM_N-1)*$STIM_VAR ) / ($CONTROL_N + $STIM_N - 2)" | bc -l)
POOLED_SD=$(echo "scale=10; sqrt($POOLED_VAR)" | bc -l)

DELTA=$(echo "scale=10; $STIM_MEAN - $CONTROL_MEAN" | bc -l)
COHEN_D=$(echo "scale=10; $DELTA / $POOLED_SD" | bc -l)

SE=$(echo "scale=10; sqrt(1/$CONTROL_N + 1/$STIM_N)" | bc -l)
T_STAT=$(echo "scale=10; $DELTA / ($POOLED_SD * $SE)" | bc -l)

ABS_T=$(echo "scale=10; if ($T_STAT < 0) { -$T_STAT } else { $T_STAT }" | bc -l)
T2=$(echo "scale=10; $ABS_T * $ABS_T" | bc -l)
PI=$(echo "scale=10; 4 * a(1)" | bc -l)
PHI=$(echo "scale=10; e(-$T2 / 2) / sqrt(2 * $PI)" | bc -l)
P_VALUE=$(echo "scale=10; 2 * $PHI / $ABS_T" | bc -l)

CAP_P=$(echo "scale=10; if ($P_VALUE < 0.000001) { 0.000001 } else { $P_VALUE }" | bc -l)

cat > "$OUTPUT_FILE" << EOH
{
  "p_value": $CAP_P,
  "cohen_d": $COHEN_D,
  "group_means": {
    "control": $CONTROL_MEAN,
    "stimulus": $STIM_MEAN
  },
  "group_stds": {
    "control": $CONTROL_SD,
    "stimulus": $STIM_SD
  }
}
EOH

rm -f /tmp/control_data.txt /tmp/stim_data.txt

echo "Analysis complete. Output: $OUTPUT_FILE"