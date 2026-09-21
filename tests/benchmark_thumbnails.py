"""Read-only native timing: PYTHONPATH=. python tests/benchmark_thumbnails.py IMAGE.jpg.

BENCH_MODE=browser|open|save selects a fresh process per application identity.
Nine links to one supplied photo isolate thumbnail decoding/scheduling. Cold
means an empty app thumbnail cache, not cold OS/NAS caches. Timings are local
measurements, not fixed CI thresholds.
"""
import argparse
import json,os,tempfile,time
from pathlib import Path
from unittest.mock import patch
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication,PickerWindow
from omarchy_file_picker.thumbnail_widgets import SCHEDULER
from gi.repository import GLib

def settle():
 loop=GLib.MainLoop();GLib.timeout_add(5,lambda:loop.quit() or False);loop.run()
def until(fn):
 deadline=time.monotonic()+60
 while not fn() and time.monotonic()<deadline:settle()
 assert fn(),'timeout'
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('image',type=Path)
args=parser.parse_args()
photo=args.image.resolve(strict=True)
assert photo.is_file(), photo
mode=os.environ.get('BENCH_MODE','browser')
assert mode in {'browser','open','save'},mode

with tempfile.TemporaryDirectory(prefix='gudfiles-bench-') as tmp,patch.object(Path,'home',return_value=Path(tmp)):
 root=Path(tmp); folder=root/'photos';folder.mkdir()
 for n in range(9):(folder/f'{n:02}.jpg').symlink_to(photo)
 config=root/'.config/omarchy-file-picker';config.mkdir(parents=True);(config/'preferences.json').write_text(json.dumps({'view_mode':'grid'}))
 for mode in (os.environ.get("BENCH_MODE", "browser"),):
  explorer = mode == "browser"
  for cache in (root/'.cache/omarchy-file-picker/thumbnails-v2').glob('*.png'):cache.unlink()
  request=PickerRequest(current_folder=folder,explorer=explorer,mode='save' if mode=='save' else 'open',title='Thumbnail timing QA')
  app=PickerApplication(request,None);app.register(None)
  for temperature in ('cold','warm'):
   start=time.perf_counter(); window=PickerWindow(app,request,None);window.present()
   until(lambda:any(w.loaded for w in SCHEDULER.widgets));first=time.perf_counter()-start
   until(lambda:len([w for w in SCHEDULER.widgets if w.in_view()])>0 and all(w.loaded for w in SCHEDULER.widgets if w.in_view()))
   total=time.perf_counter()-start; visible=len([w for w in SCHEDULER.widgets if w.in_view()])
   print(json.dumps(dict(mode=mode,cache=temperature,first=round(first,3),all_visible=round(total,3),visible=visible)),flush=True)
   window.destroy();until(lambda:SCHEDULER.running==0 and not SCHEDULER.widgets)
