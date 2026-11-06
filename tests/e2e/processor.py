import sys,time
from pathlib import Path
root=Path(sys.argv[1])
print('SLAM_EVENT {"stage":"mapping","processed":0,"total":8}',flush=True)
time.sleep(.4)
(root/'manifest.tmp').write_bytes((root/'controlled.json').read_bytes())
(root/'manifest.tmp').replace(root/'manifest.json')
