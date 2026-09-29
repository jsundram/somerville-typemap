# /// script
# requires-python = ">=3.11"
# ///
"""Bundle out/layers/*.svg into a single self-contained viewer page.

Each layer is a hidden <img> (data: URI) used as a vector source; the
visible viewport is drawn onto one canvas with ctx.drawImage at the
current zoom. Chrome replays an SVG <img> in full for every raster tile
(~430 ms/tile at high zoom — measured 2026-09-29), so letting the
compositor tile huge scaled <img>s was the slowness; one clipped
drawImage per settle costs ~20–250 ms total. Checkboxes toggle layers.
"""

import base64
import re
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "out/viewer.html"

LAYER_META = {
    "L1_basemap": ("Basemap", "schematic reference", True),
    "L2_neighborhoods": ("Neighborhoods", "region tints + name wash", False),
    "L3_transit": ("Transit", "T stops + Community Path", True),
    "L4_adjacent": ("Adjacent towns", "Medford, Cambridge, Charlestown…", False),
    "L5_heroes": ("Hero labels", "fitted neighborhood typography", False),
    "L6_typography": ("Roads / parks / water", "the all-text layer", False),
    "L7_boundaries": ("Boundaries", "the administrative lines", True),
    "L8_annotations": ("Boundary annotations", "what demarcates each border", True),
    "L9_perceived": ("Perceived borders", "the line locals draw", True),
}

# Stacking, bottom → top. Heroes are topmost.
Z_ORDER = ["L1_basemap", "L4_adjacent", "L2_neighborhoods", "L7_boundaries",
           "L8_annotations", "L9_perceived", "L6_typography", "L3_transit",
           "L5_heroes"]


def main():
    svgs = {f.stem: f for f in (ROOT / "out/layers").glob("L*.svg")}
    ordered = [svgs[k] for k in Z_ORDER if k in svgs]
    w, h = 3400, int(re.search(r'height="(\d+)"', ordered[0].read_text()).group(1))

    imgs, boxes = [], []
    for f in ordered:
        key = f.stem
        title, hint, on = LAYER_META.get(key, (key, "", True))
        uri = "data:image/svg+xml;base64," + base64.b64encode(f.read_bytes()).decode()
        checked = " checked" if on else ""
        imgs.append(f'<img id="{key}" src="{uri}" alt="{title}"'
                    f' data-on="{int(on)}">')
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
  #sources {{ display:none; }}
  #stage canvas {{ position:absolute; left:0; top:0; transform-origin:0 0;
                   will-change:transform; pointer-events:none; }}
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
<div id="sources">{''.join(imgs)}</div>
<div id="stage"><canvas id="overview"></canvas><canvas id="view"></canvas></div>
<div id="panel">
  <h1><b>somerville</b> typemap</h1>
  {''.join(boxes)}
  <div id="legend">borders run along:<br>
    <i style="color:#3a3a3a">— street</i><i style="color:#8a5fbf">╌ rail</i><i style="color:#2f8f4e">— path</i><i style="color:#3f7fbf">— water</i><i style="color:#b0a898">·· nothing</i>
  </div>
  <p>scroll to zoom · drag to pan</p>
</div>
<script>
  // Pan/zoom strategy. Layers are hidden SVG <img>s used as vector
  // sources. Two canvases:
  //  - overview: the whole map once at ~2k px (re-drawn on layer toggle);
  //    it fills in during gestures, soft but instant;
  //  - view: the viewport plus a margin, drawn crisp at the current zoom
  //    once a gesture settles ("bake").
  // During a gesture only CSS transforms change (compositor-only).
  const stage=document.getElementById('stage');
  const ov=document.getElementById('overview'), vw=document.getElementById('view');
  const W={w}, H={h}, PAPER='#faf7f0', M=0.25;  // bake margin, viewport fractions
  const OVS=Math.min(1, 2048/W);                 // overview scale
  const dpr=Math.min(devicePixelRatio||1, 2);
  const imgs=[...document.querySelectorAll('#sources img')];
  const on=Object.fromEntries(imgs.map(i=>[i.id, i.dataset.on==='1']));
  let s=1, tx=0, ty=0, bk={{s:1, ox:0, oy:0}}, bakeTimer=null, ready=false;

  function drawLayers(ctx) {{
    ctx.fillStyle=PAPER; ctx.fillRect(0,0,W,H);
    for (const i of imgs) if (on[i.id]) ctx.drawImage(i,0,0,W,H);
  }}
  function drawOverview() {{
    ov.width=Math.round(W*OVS); ov.height=Math.round(H*OVS);
    const c=ov.getContext('2d'); c.setTransform(OVS,0,0,OVS,0,0); drawLayers(c);
  }}
  function bake() {{
    if (!ready) return;
    const cw=stage.clientWidth, ch=stage.clientHeight;
    const mx=cw*M, my=ch*M, bw=cw+2*mx, bh=ch+2*my;
    vw.width=Math.round(bw*dpr); vw.height=Math.round(bh*dpr);
    vw.style.width=bw+'px'; vw.style.height=bh+'px';
    const c=vw.getContext('2d');
    c.setTransform(dpr,0,0,dpr,0,0); c.clearRect(0,0,bw,bh);
    c.save(); c.translate(mx+tx, my+ty); c.scale(s,s);
    c.beginPath(); c.rect(0,0,W,H); c.clip();  // paper only over the map
    drawLayers(c); c.restore();
    bk={{s, ox:-mx-tx, oy:-my-ty}};  // canvas origin, relative to the map origin on screen
    apply();
  }}
  function apply() {{
    ov.style.transform=`translate(${{tx}}px,${{ty}}px) scale(${{s/OVS}})`;
    const k=s/bk.s;  // canvas px were baked at bk.s; map origin is now at (tx,ty)
    vw.style.transform=`translate(${{tx+bk.ox*k}}px,${{ty+bk.oy*k}}px) scale(${{k}})`;
  }}
  const queueBake=()=>{{ clearTimeout(bakeTimer); bakeTimer=setTimeout(bake, 150); }};
  function fit() {{
    s=Math.min(stage.clientWidth/W, stage.clientHeight/H)||.3;
    tx=(stage.clientWidth-W*s)/2; ty=(stage.clientHeight-H*s)/2; apply(); bake();
  }}
  Promise.all(imgs.map(i=>i.decode().catch(()=>{{}}))).then(()=>{{
    ready=true; drawOverview(); fit(); }});
  addEventListener('resize', fit);
  stage.addEventListener('wheel', e=>{{ e.preventDefault();
    const k=Math.exp(-e.deltaY*0.0015), r=stage.getBoundingClientRect();
    const x=e.clientX-r.left, y=e.clientY-r.top;
    const ns=Math.min(Math.max(s*k, .05), 12), kk=ns/s;
    tx=x-(x-tx)*kk; ty=y-(y-ty)*kk; s=ns; apply(); queueBake(); }}, {{passive:false}});
  let drag=null;
  stage.addEventListener('pointerdown', e=>{{ drag={{x:e.clientX-tx, y:e.clientY-ty}};
    stage.setPointerCapture(e.pointerId); }});
  stage.addEventListener('pointermove', e=>{{ if(drag){{
    tx=e.clientX-drag.x; ty=e.clientY-drag.y; apply(); }} }});
  stage.addEventListener('pointerup', ()=>{{ drag=null; queueBake(); }});
  document.querySelectorAll('#panel input').forEach(cb=>cb.addEventListener('change', ()=>{{
    on[cb.dataset.layer]=cb.checked; drawOverview(); bake(); }}));
</script>
""")
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
