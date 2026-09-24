#!/bin/bash
# issue241 R8-I3 v2 canonical chain at head b6148de (dispatch comment 5806929798).
# Each phase gates on the next; RC files retained per phase.
set -u
C=/home/hermes/is241-campaign-v2
cd /home/hermes/is241-repo || { echo 129 > $C/logs/chain.exit; exit 129; }

run() {
  phase=$1; tmo=$2
  timeout $tmo python3 $C/run_phase.py "$phase" > $C/logs/$phase.log 2>&1
  rc=$?
  echo $rc > $C/logs/$phase.exit
  echo "$(date -Is) phase $phase rc=$rc" >> $C/logs/chain.log
  if [ $rc -ne 0 ]; then echo $rc > $C/logs/chain.exit; exit $rc; fi
}

echo "$(date -Is) chain start head=$(git rev-parse HEAD)" >> $C/logs/chain.log
run phase1 3600
run phase2 21600
run phase3 64800
run phase4 600
echo "$(date -Is) chain complete" >> $C/logs/chain.log
echo 0 > $C/logs/chain.exit
exit 0
