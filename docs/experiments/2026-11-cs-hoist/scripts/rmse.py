# rmse.py <dir>: RMSE (% of full scale) between the screenshots imgab.sh writes. Needs Pillow.
import sys, math
from PIL import Image, ImageChops, ImageStat
d = sys.argv[1]
def L(n): return Image.open(f'{d}/{n}.png').convert('RGB')
def r(a, b):
    x = ImageChops.difference(L(a), L(b)); s = ImageStat.Stat(x)
    return math.sqrt(sum(s.sum2) / (3 * x.size[0] * x.size[1])) / 255 * 100
P = [('on1-0','on1-1','consecutive, on'), ('off-0','off-1','consecutive, off'), ('on1-2','on2-0','on vs on (later)'),
     ('off-2','off2-0','off vs off (later)'), ('on1-2','off-0','on -> off'), ('off-2','on2-0','off -> on'), ('on2-2','off2-0','on -> off')]
for a, b, t in P: print(f'{t:22s} {a} vs {b}: {r(a, b):.3f}%')
