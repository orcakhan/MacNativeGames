#!/bin/zsh
# measure.sh <botw|totk> <tag> [KEY=VAL ...]: one windowed launch (TOTK_DEBUG_LOG=1, TOTK_INPUT_FILE), newest save loaded with
# three A presses, 150 s warm-up, 60 s of 300-frame windows, a 3-frame pass dump, a screenshot, close. Results in
# $OUT/<game>-<tag>/summary.txt. Used for the ABBA runs (TOTK_CS_HOIST=0/1) of 2026-11-19.
set -u
OUT=${OUT:-$HOME/MacNativeGames-work/cs-hoist-runs}
REPO=${REPO:-$(cd "$(dirname $0)/../../../.." && pwd)}
game=$1; tag=$2; shift 2
case $game in
  botw) app="$HOME/Applications/Breath of the Wild.app"; exe=BotW; log=$HOME/Library/Logs/MacNativeGames/botw.log; gpu_min=3 ;;
  totk) app="/Applications/Tears of the Kingdom.app"; exe=TOTK; log=$HOME/Library/Logs/MacNativeGames/totk.log; gpu_min=6 ;;
  *) echo "game: botw or totk" >&2; exit 2 ;;
esac
out=$OUT/$game-$tag; rm -rf $out; mkdir -p $out
cmds=$out/cmds.txt; : > $cmds
export LC_ALL=C
fail() { echo "FAIL: $*" | tee -a $out/summary.txt; echo close >> $cmds; exit 1; }
nwin() { local c; c=$(grep -c "计时 至帧" $log 2>/dev/null); echo ${c:-0}; }
lastgpu() { grep "计时 至帧" $log | tail -1 | sed -E 's/.*GPU p50 ([0-9.]+).*/\1/'; }
wait_until() { local limit=$1; shift; local t0=$(date +%s); until eval "$@"; do (( $(date +%s) - t0 > limit )) && return 1; sleep 1; done; return 0; }

pgrep -x $exe >/dev/null && { echo "FAIL: $exe already running" >&2; exit 1; }
commit=$(plutil -extract MNGSourceCommit raw "$app/Contents/Info.plist" 2>/dev/null)
echo "game=$game tag=$tag commit=$commit env=$*" > $out/summary.txt
t0=$(date +%s)
( cd "$app/Contents/MacOS" && env TOTK_DEBUG_LOG=1 TOTK_INPUT_FILE=$cmds "$@" ./$exe > $out/launch.out 2>&1 ) &
wait_until 60 '[ -f $log ] && [ $(stat -f %m $log) -ge $t0 ]' || fail "no new log"
wait_until 240 '[ $(nwin) -ge 2 ]' || fail "no frame windows"
sleep 2; echo "key 38 200" >> $cmds; sleep 4; echo "key 38 200" >> $cmds; sleep 3; echo "key 38 200" >> $cmds
wait_until 240 'g=$(lastgpu); [ -n "$g" ] && [ $(echo "$g > $gpu_min" | bc) -eq 1 ]' || fail "the save did not load (GPU p50 never above $gpu_min ms)"
echo "loaded after $(( $(date +%s) - t0 )) s" >> $out/summary.txt
sleep 150
n0=$(nwin); sleep 60
grep "计时 至帧" $log | tail -n +$((n0 + 1)) > $out/windows.txt
grep "翻译细项" $log | tail -1 > $out/submit.txt
l0=$(grep -c "" $log); echo "passdump 3" >> $cmds; n1=$(nwin)
wait_until 60 '[ $(nwin) -ge $((n1 + 2)) ]' || fail "pass dump did not finish"
tail -n +$l0 $log | grep "^\[pass\]" > $out/passdump.txt
echo "wshot $out/shot.png" >> $cmds; wait_until 30 '[ -s $out/shot.png ]'
grep -E "cs-hoist|TOTK_CS_HOIST|moved ahead" $log | tail -5 > $out/hoist.txt
echo close >> $cmds; wait_until 60 '! pgrep -x $exe >/dev/null' || echo "warning: $exe still running" >> $out/summary.txt
cp $log $out/log
echo "window covered events: $(grep -c "window covered" $log)" >> $out/summary.txt   # >0: macOS stopped presenting, rerun

# the rp_end() lines inside dispatch() of the app's source: a pass ended there was split by a compute dispatch
src=$(git -C $REPO show "${commit%+dirty}:games/totk/third_party/d2r_gfx/gfx/nvn/nvn_mtl.m" 2>/dev/null) || src=$(cat $REPO/games/totk/third_party/d2r_gfx/gfx/nvn/nvn_mtl.m)
dlines=$(print -r -- "$src" | awk '/^static void dispatch\(const p_dispatch \*dp\) \{/ {inside=1} inside && /rp_end\(\)/ {printf "%s|", NR} inside && /^\}/ {exit}')
dlines=${dlines%|}
{
  sed -E 's/.*帧时间 p50 ([0-9.]+) \/ p95 ([0-9.]+).*NVN 提交\+出图 p50 ([0-9.]+).*GPU p50 ([0-9.]+) \/ p95 ([0-9.]+).*/\1 \2 \3 \4 \5/' $out/windows.txt |
    awk '{f+=$1; g+=$4; s+=$3; n++; if(fmin==""||$1<fmin)fmin=$1; if($1>fmax)fmax=$1; if(gmin==""||$4<gmin)gmin=$4; if($4>gmax)gmax=$4}
         END{printf "windows %d: frame p50 %.2f ms (%.1f fps) [%.2f..%.2f]; GPU p50 %.2f [%.2f..%.2f]; submit+present p50 %.2f\n", n, f/n, 1000/(f/n), fmin, fmax, g/n, gmin, gmax, s/n}'
  sed -E 's/.*每帧提交 周期 ([0-9.]+) M.*/submit cycles per frame: \1 M/' $out/submit.txt
  echo "dispatch rp_end lines: $dlines"
  awk -v L="$dlines" '
    BEGIN { n = split(L, a, "|"); for (i = 1; i <= n; i++) dl["nvn_mtl.m:" a[i]] = 1 }
    $4=="P" { k=$5; t[k]=t[k] " " $6 ":" $7 "/" $9 }
    $4=="Z" && /pass_end/ { s=$0; sub(/.*at=/,"",s); es[$5]=s; frames[$2]=1; passes++ }
    $4=="H" { moved++ }
    END { nf=0; for (f in frames) nf++
          for (k in es) if (es[k] in dl) { if (t[k]==t[k+1]) same++; else diff++ }
          printf "frames %d: passes/frame %.1f; ended by dispatch, same targets next %.1f/frame, other targets %.1f/frame; H lines (moved) %.1f/frame\n", nf, passes/nf, same/nf, diff/nf, moved/nf }' $out/passdump.txt
} >> $out/summary.txt
cat $out/summary.txt
