# /// script
# requires-python = ">=3.11"
# ///
"""Bundle out/layers/*.svg into a single self-contained viewer page.

Each layer becomes a stacked <img> with a data: URI — the browser treats
them as cached raster surfaces, so pan/zoom stays fast no matter how many
text elements a layer contains. Checkboxes toggle layers independently.
"""

import base64
import re
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "out/viewer.html"

LAYER_META = {
    "L1_basemap": ("Basemap", "schematic reference", False),
    "L2_neighborhoods": ("Neighborhoods", "region tints + name wash", True),
    "L3_transit": ("Transit", "T stops + Community Path", True),
    "L4_adjacent": ("Adjacent towns", "Medford, Cambridge, Charlestown…", True),
    "L5_heroes": ("Hero labels", "fitted neighborhood typography", True),
    "L6_typography": ("Roads / parks / water", "the all-text layer", True),
}


def main():
    svgs = sorted((ROOT / "out/layers").glob("L*.svg"))
    w, h = 3400, int(re.search(r'height="(\d+)"', svgs[0].read_text()).group(1))

    imgs, boxes = [], []
    for f in svgs:
        key = f.stem
        title, hint, on = LAYER_META.get(key, (key, "", True))
        uri = "data:image/svg+xml;base64," + base64.b64encode(f.read_bytes()).decode()
        hidden = "" if on else " hidden"
        checked = " checked" if on else ""
        imgs.append(f'<img id="{key}" src="{uri}" alt="{title}"{hidden}>')
        boxes.append(f'<label><input type="checkbox" data-layer="{key}"{checked}>'
                     f'<b>{title}</b><span>{hint}</span></label>')

    OUT.write_text(f"""<meta charset="utf-8">
<title>Somerville Typemap</title>
<style>
  :root {{ --ground:#2b2926; --ink:#e8e2d6; --dim:#9a938a; --accent:#d13c8f; --panel:#3a3733; }}
  :root[data-theme="light"] {{ --ground:#e5e0d5; --ink:#2b2926; --dim:#6b655c; --panel:#f2ede2; }}
  @media (prefers-color-scheme: light) {{
    :root:not([data-theme="dark"]) {{ --ground:#e5e0d5; --ink:#2b2926; --dim:#6b655c; --panel:#f2ede2; }}
  }}
  html,body {{ margin:0; height:100%; }}
  body {{ background:var(--ground); color:var(--ink); overflow:hidden;
          font:14px/1.5 "Avenir Next","Helvetica Neue",sans-serif; }}
  #stage {{ position:absolute; inset:0; overflow:hidden; cursor:grab; touch-action:none; }}
  #stage:active {{ cursor:grabbing; }}
  #map {{ position:absolute; width:{w}px; height:{h}px; transform-origin:0 0;
          background:#faf7f0; box-shadow:0 8px 40px rgba(0,0,0,.35); }}
  #map img {{ position:absolute; inset:0; width:100%; height:100%; pointer-events:none; }}
  #panel {{ position:absolute; top:12px; left:12px; background:var(--panel);
            border-radius:6px; padding:.8rem 1rem; box-shadow:0 4px 20px rgba(0,0,0,.25);
            display:flex; flex-direction:column; gap:.35rem; max-width:240px; }}
  #panel h1 {{ font-size:.85rem; margin:0 0 .3rem; letter-spacing:.12em; text-transform:uppercase; }}
  #panel h1 b {{ color:var(--accent); }}
  #panel label {{ display:flex; align-items:baseline; gap:.5rem; cursor:pointer; font-size:.82rem; }}
  #panel label span {{ color:var(--dim); font-size:.72rem; margin-left:.3rem; }}
  #panel p {{ margin:.4rem 0 0; color:var(--dim); font-size:.72rem; }}
</style>
<div id="stage"><div id="map">{''.join(imgs)}</div></div>
<div id="panel">
  <h1><b>somerville</b> typemap</h1>
  {''.join(boxes)}
  <p>scroll to zoom · drag to pan</p>
</div>
<script>
  const stage=document.getElementById('stage'), map=document.getElementById('map');
  let s=1, tx=0, ty=0;
  const apply=()=>map.style.transform=`translate(${{tx}}px,${{ty}}px) scale(${{s}})`;
  const fit=()=>{{ s=Math.min(stage.clientWidth/{w}, stage.clientHeight/{h});
                   tx=(stage.clientWidth-{w}*s)/2; ty=(stage.clientHeight-{h}*s)/2; apply(); }};
  addEventListener('load', fit); addEventListener('resize', fit);
  stage.addEventListener('wheel', e=>{{ e.preventDefault();
    const k=Math.exp(-e.deltaY*0.0015), r=stage.getBoundingClientRect();
    const x=e.clientX-r.left, y=e.clientY-r.top;
    tx=x-(x-tx)*k; ty=y-(y-ty)*k; s*=k; apply(); }}, {{passive:false}});
  let drag=null;
  stage.addEventListener('pointerdown', e=>{{ drag={{x:e.clientX-tx, y:e.clientY-ty}};
    stage.setPointerCapture(e.pointerId); }});
  stage.addEventListener('pointermove', e=>{{ if(drag){{ tx=e.clientX-drag.x; ty=e.clientY-drag.y; apply(); }} }});
  stage.addEventListener('pointerup', ()=>drag=null);
  document.querySelectorAll('#panel input').forEach(cb=>cb.addEventListener('change', ()=>
    document.getElementById(cb.dataset.layer).hidden=!cb.checked));
  fit();
</script>
""")
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
