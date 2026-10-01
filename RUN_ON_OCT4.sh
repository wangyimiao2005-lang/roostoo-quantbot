#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="src:research${PYTHONPATH:+:$PYTHONPATH}"
python research/run_final_precompetition_gate.py
printf '\n=== ACTIVE STRATEGY ===\n'
cat frozen/competition_strategy/ACTIVE_STRATEGY.json
printf '\n=== FINAL GATE REPORT ===\n'
cat results/final_precompetition_gate/FINAL_PRECOMPETITION_GATE_REPORT.md
