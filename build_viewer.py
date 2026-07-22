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
    "L7_boundaries": ("Boundaries", "city outline + neighborhood borders", True),
}

# Stacking, bottom → top. Heroes are topmost.
Z_ORDER = ["L1_basemap", "L4_adjacent", "L2_neighborhoods", "L7_boundaries",
           "L6_typography", "L3_transit", "L5_heroes"]


def main():
    svgs = {f.stem: f for f in (ROOT / "out/layers").glob("L*.svg")}
    ordered = [svgs[k] for k in Z_ORDER if k in svgs]
    w, h = 3400, int(re.search(r'height="(\d+)"', ordered[0].read_text()).group(1))

    imgs, boxes = [], []
    for f in ordered:
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
  #map {{ position:absolute; left:0; top:0; width:{w}px; height:{h}px;
          transform-origin:0 0; will-change:transform;
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
  #legend {{ margin-top:.4rem; font-size:.72rem; color:var(--dim); }}
  #legend i {{ font-style:normal; font-weight:700; margin-right:.45em; white-space:nowrap; }}
</style>
<div id="stage"><div id="map">{''.join(imgs)}</div></div>
<div id="panel">
  <h1><b>somerville</b> typemap</h1>
  {''.join(boxes)}
  <div id="legend">borders run along:<br>
    <i style="color:#3a3a3a">— street</i><i style="color:#8a5fbf">╌ rail</i><i style="color:#2f8f4e">— path</i><i style="color:#3f7fbf">— water</i><i style="color:#b0a898">·· nothing</i>
  </div>
  <p>scroll to zoom · drag to pan</p>
</div>
<script>
  // Pan/zoom strategy: during a gesture, only a compositor transform
  // changes (fast, but scaling above the baked size looks soft). When
  // the gesture settles, "bake": relayout the layer images at the new
  // size so the browser re-rasterizes the SVGs crisply — once, not per
  // frame. This keeps interaction smooth despite ~10k text glyphs.
  const stage=document.getElementById('stage'), map=document.getElementById('map');
  const W={w}, H={h};
  let s=1, tx=0, ty=0, baked=1, bakeTimer=null;
  const apply=()=>map.style.transform=`translate(${{tx}}px,${{ty}}px) scale(${{s/baked}})`;
  const bake=()=>{{ baked=s; map.style.width=(W*s)+'px'; map.style.height=(H*s)+'px'; apply(); }};
  const queueBake=()=>{{ clearTimeout(bakeTimer); bakeTimer=setTimeout(bake, 250); }};
  const fit=()=>{{ s=Math.min(stage.clientWidth/W, stage.clientHeight/H)||.3;
                   tx=(stage.clientWidth-W*s)/2; ty=(stage.clientHeight-H*s)/2; bake(); }};
  addEventListener('load', fit); addEventListener('resize', fit);
  stage.addEventListener('wheel', e=>{{ e.preventDefault();
    const k=Math.exp(-e.deltaY*0.0015), r=stage.getBoundingClientRect();
    const x=e.clientX-r.left, y=e.clientY-r.top;
    const ns=Math.min(Math.max(s*k, .05), 8);
    const kk=ns/s;
    tx=x-(x-tx)*kk; ty=y-(y-ty)*kk; s=ns; apply(); queueBake(); }}, {{passive:false}});
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
