#!/bin/zsh
# imgab.sh: one BotW session (hoist on), newest save, 90 s, then groups of 3 consecutive screenshots with
# "flag cs_hoist" 1, 0, 1, 0 (3 s after each switch). Compare with rmse.py. Result of 2026-11-19: RMSE across the
# switch 1.43-1.45%, same setting the same time apart 1.66-1.74%, consecutive frames 0.12-0.16% -> no visible change.
set -u
OUT=${OUT:-$HOME/MacNativeGames-work/cs-hoist-runs}
app="$HOME/Applications/Breath of the Wild.app"; log=$HOME/Library/Logs/MacNativeGames/botw.log
out=$OUT/img; rm -rf $out; mkdir -p $out; cmds=$out/cmds.txt; : > $cmds; export LC_ALL=C
nwin() { local c; c=$(grep -c "计时 至帧" $log 2>/dev/null); echo ${c:-0}; }
pgrep -x BotW >/dev/null && { echo "BotW running"; exit 1; }
t0=$(date +%s)
( cd "$app/Contents/MacOS" && env TOTK_DEBUG_LOG=1 TOTK_INPUT_FILE=$cmds TOTK_CS_HOIST=1 ./BotW > $out/launch.out 2>&1 ) &
until [ -f $log ] && [ $(stat -f %m $log) -ge $t0 ] && [ $(nwin) -ge 2 ]; do sleep 1; done
sleep 2; echo "key 38 200" >> $cmds; sleep 4; echo "key 38 200" >> $cmds; sleep 3; echo "key 38 200" >> $cmds
sleep 90
for g in on1 off on2 off2; do
  case $g in off*) echo "flag cs_hoist 0" >> $cmds;; *) echo "flag cs_hoist 1" >> $cmds;; esac
  sleep 3; echo "shotn 3 $out/$g-%d.png" >> $cmds; sleep 3
done
sleep 2; grep -E "flag\] cs_hoist|cs-hoist\] frame" $log | tail -8 > $out/flags.txt
echo close >> $cmds; until ! pgrep -x BotW >/dev/null; do sleep 1; done
ls $out
