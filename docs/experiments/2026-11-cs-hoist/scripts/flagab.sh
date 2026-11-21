#!/bin/zsh
# flagab.sh <tag>: one BotW session, newest save via three A presses, 150 s warm-up, then the hoist switched with
# "flag cs_hoist" in the order off on on off off on on off, 30 s each (first 5 s dropped); frame/GPU per state.
# Written for the particle-scene check that was never run (2026-11-19).
set -u
OUT=${OUT:-$HOME/MacNativeGames-work/cs-hoist-runs}
app="$HOME/Applications/Breath of the Wild.app"; log=$HOME/Library/Logs/MacNativeGames/botw.log
out=$OUT/flag-$1; rm -rf $out; mkdir -p $out; cmds=$out/cmds.txt; : > $cmds; export LC_ALL=C
nwin() { local c; c=$(grep -c "计时 至帧" $log 2>/dev/null); echo ${c:-0}; }
pgrep -x BotW >/dev/null && { echo "BotW running"; exit 1; }
t0=$(date +%s)
( cd "$app/Contents/MacOS" && env TOTK_DEBUG_LOG=1 TOTK_INPUT_FILE=$cmds ./BotW > $out/launch.out 2>&1 ) &
until [ -f $log ] && [ $(stat -f %m $log) -ge $t0 ] && [ $(nwin) -ge 2 ]; do sleep 1; done
sleep 2; echo "key 38 200" >> $cmds; sleep 4; echo "key 38 200" >> $cmds; sleep 3; echo "key 38 200" >> $cmds
sleep 150
for v in 0 1 1 0 0 1 1 0; do
  echo "flag cs_hoist $v" >> $cmds; sleep 5; n0=$(nwin); sleep 25
  grep "计时 至帧" $log | tail -n +$((n0 + 1)) | sed -E "s/.*帧时间 p50 ([0-9.]+) .*GPU p50 ([0-9.]+) .*/$v \1 \2/" >> $out/seg.txt
  echo "--" >> $out/seg.txt
done
echo "wshot $out/shot.png" >> $cmds; sleep 3
grep -E "cs-hoist\] frame" $log | tail -1 > $out/hoist.txt
echo close >> $cmds; until ! pgrep -x BotW >/dev/null; do sleep 1; done
awk '$1=="0"||$1=="1"{f[$1]+=$2; g[$1]+=$3; n[$1]++} END{for(v=0;v<=1;v++) printf "hoist=%d: %d windows, frame p50 %.3f ms, GPU p50 %.3f ms\n", v, n[v], f[v]/n[v], g[v]/n[v]}' $out/seg.txt | tee $out/summary.txt
echo "window covered events: $(grep -c "window covered" $log)" >> $out/summary.txt
