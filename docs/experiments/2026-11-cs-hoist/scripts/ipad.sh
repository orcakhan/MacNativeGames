#!/bin/zsh
# ipad.sh NAME HOIST(0|1): BotW on the iPad (A16) over devicectl (Wi-Fi works), autoload, default frame cap; log pulled
# after 150 s and 270 s; the measurement is what was written between the two pulls; then the app is ended.
# Run a warm-up start first after installing a new build (pipelines), then off on on off with 120 s rests.
set -u
OUT=${OUT:-$HOME/MacNativeGames-work/cs-hoist-runs}
D=${IPAD_UDID:?set IPAD_UDID}; B=${IPAD_BUNDLE:-org.macnativegames.botw.7ha92nha9b}
name=$1; h=$2; o=$OUT/ipad-$name; mkdir -p $o; export LC_ALL=C
pull() { xcrun devicectl device copy from --device $D --domain-type appDataContainer --domain-identifier $B --source Documents/log.txt --destination $1 >/dev/null 2>&1; }
xcrun devicectl device process launch --device $D --terminate-existing --json-output $o/launch.json \
  --environment-variables "{\"TOTK_DEBUG_LOG\":\"1\",\"TOTK_START_SCREEN\":\"0\",\"TOTK_AUTOLOAD\":\"1\",\"TOTK_CS_HOIST\":\"$h\"}" $B > $o/launch.out 2>&1
pid=$(python3 -I -c "import json,sys; print(json.load(open(sys.argv[1]))['result']['process']['processIdentifier'])" $o/launch.json 2>/dev/null)
sleep 150; pull $o/log0.txt; l0=$(grep -ac "" $o/log0.txt)   # if this pull fails, use only the last 12 windows
sleep 120; pull $o/log.txt
xcrun devicectl device capture screenshot --device $D --destination $o/shot.png >/dev/null 2>&1
[ -n "$pid" ] && xcrun devicectl device process terminate --device $D --pid $pid >/dev/null 2>&1
tail -n +$((l0 + 1)) $o/log.txt > $o/tail.txt
grep -a "计时 至帧" $o/tail.txt > $o/windows.txt; grep -a "翻译细项" $o/tail.txt > $o/submit.txt
{ echo "$name hoist=$h pid=$pid windows=$(grep -c '' $o/windows.txt)"
  sed -E 's/.*帧时间 p50 ([0-9.]+) \/ p95 ([0-9.]+).*GPU p50 ([0-9.]+) \/ p95 ([0-9.]+).*/\1 \3/' $o/windows.txt | awk '{f+=$1;g+=$2;n++} END{if(n) printf "frame p50 %.2f ms, GPU p50 %.2f ms (%d windows)\n", f/n, g/n, n}'
  tail -2 $o/submit.txt | cut -c1-300
  grep -a "cs-hoist\] frame" $o/log.txt | tail -1 | cut -c1-260; } > $o/summary.txt
cat $o/summary.txt
