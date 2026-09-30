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
  #views {{ position:absolute; inset:0; }}
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
<div id="stage"><canvas id="overview"></canvas><div id="views"></div></div>
<div id="panel">
  <h1><b>somerville</b> typemap</h1>
  {''.join(boxes)}
  <div id="legend">borders run along:<br>
    <i style="color:#3a3a3a">— street</i><i style="color:#8a5fbf">╌ rail</i><i style="color:#2f8f4e">— path</i><i style="color:#3f7fbf">— water</i><i style="color:#b0a898">·· nothing</i>
  </div>
  <p>scroll to zoom · drag to pan</p>
</div>
<script>
  // Pan/zoom + layers, tuned for many heavy text layers.
  // Layers are hidden SVG <img>s used as vector sources; drawing one onto
  // a canvas is the expensive step (~10–120 ms/layer), so nothing redraws
  // more than it must:
  //  - overview: each layer rasterized ONCE at ~2k px (cached per layer),
  //    composited under everything; soft but instant during gestures;
  //  - view: one canvas per layer (viewport + margin, crisp) plus a paper
  //    canvas; each remembers the zoom it was baked at, so a stale canvas
  //    just scales until its turn;
  //  - bake: after a gesture settles, layers redraw ONE PER FRAME (a new
  //    gesture cancels the rest) — the page never freezes;
  //  - toggle: hiding is display-only; showing draws just that layer.
  const stage=document.getElementById('stage'), views=document.getElementById('views');
  const ov=document.getElementById('overview');
  // CPU-backed canvases: replaying an SVG with thousands of text runs is
  // ~40× faster in software than on a GPU canvas at high zoom (measured:
  // roads layer 2.9 s → ~80 ms at 12×)
  const CTX={{willReadFrequently:true}};
  const W={w}, H={h}, PAPER='#faf7f0', M=0.25;
  const OVS=Math.min(1, 2048/W), dpr=Math.min(devicePixelRatio||1, 2);
  const imgs=[...document.querySelectorAll('#sources img')];
  const mk=()=>{{ const c=document.createElement('canvas'); views.appendChild(c); return c; }};
  const paper={{cv:mk(), bk:null}};
  const L=imgs.map(i=>({{img:i, id:i.id, on:i.dataset.on==='1', cv:mk(), bk:null, ovc:null}}));
  let s=1, tx=0, ty=0, gen=0, bakeTimer=null, ready=false;

  function ovCanvas(l) {{  // this layer's cached overview raster
    if (!l.ovc) {{ timed('ov:'+l.id, ()=>{{
      l.ovc=document.createElement('canvas');
      l.ovc.width=Math.round(W*OVS); l.ovc.height=Math.round(H*OVS);
      const c=l.ovc.getContext('2d', CTX); c.setTransform(OVS,0,0,OVS,0,0);
      c.drawImage(l.img,0,0,W,H); }});
    }}
    return l.ovc;
  }}
  function drawOverview() {{  // composite cached rasters: cheap
    ov.width=Math.round(W*OVS); ov.height=Math.round(H*OVS);
    const c=ov.getContext('2d', CTX); c.fillStyle=PAPER; c.fillRect(0,0,ov.width,ov.height);
    for (const l of L) if (l.on) c.drawImage(ovCanvas(l),0,0);
  }}
  function viewBox() {{
    const cw=stage.clientWidth, ch=stage.clientHeight, mx=cw*M, my=ch*M;
    return {{mx, my, bw:cw+2*mx, bh:ch+2*my}};
  }}
  function paint(target, draw) {{  // crisp raster of the viewport+margin
    const {{mx,my,bw,bh}}=viewBox(), cv=target.cv;
    cv.width=Math.round(bw*dpr); cv.height=Math.round(bh*dpr);
    cv.style.width=bw+'px'; cv.style.height=bh+'px';
    const c=cv.getContext('2d', CTX);
    c.setTransform(dpr,0,0,dpr,0,0); c.clearRect(0,0,bw,bh);
    c.save(); c.translate(mx+tx, my+ty); c.scale(s,s);
    draw(c); c.restore();  // no clip: drawImage/fillRect stay in 0..W×H
    // (a clip rect at 12× — ~40k px wide — made one layer take 3 s)
    target.bk={{s, ox:-mx-tx, oy:-my-ty}};
    place(target);
  }}
  const T=window.__paint=[];  // timing log (inspect in devtools)
  const timed=(what,f)=>{{ const t=performance.now(); f(); T.push([what, s.toFixed(2), Math.round(performance.now()-t)]); }};
  const paintLayer=l=>timed(l.id, ()=>paint(l, c=>c.drawImage(l.img,0,0,W,H)));
  const paintPaper=()=>paint(paper, c=>{{ c.fillStyle=PAPER; c.fillRect(0,0,W,H); }});
  function place(t) {{
    if (!t.bk) {{ t.cv.style.display='none'; return; }}
    t.cv.style.display=(t===paper||t.on)?'':'none';
    const k=s/t.bk.s;
    t.cv.style.transform=`translate(${{tx+t.bk.ox*k}}px,${{ty+t.bk.oy*k}}px) scale(${{k}})`;
  }}
  function apply() {{
    ov.style.transform=`translate(${{tx}}px,${{ty}}px) scale(${{s/OVS}})`;
    place(paper); for (const l of L) place(l);
  }}
  function bake() {{  // progressive: one layer per frame, cancellable
    if (!ready) return;
    const g=++gen, todo=L.filter(l=>l.on);
    const step=()=>{{
      if (g!==gen) return;
      const l=todo.shift();
      if (l) {{ paintLayer(l); requestAnimationFrame(step); }}
      else paintPaper();  // last: hides the overview under fresh layers
    }};
    requestAnimationFrame(step);
  }}
  const queueBake=()=>{{ gen++; clearTimeout(bakeTimer); bakeTimer=setTimeout(bake, 150); }};
  function fit() {{
    s=Math.min(stage.clientWidth/W, stage.clientHeight/H)||.3;
    tx=(stage.clientWidth-W*s)/2; ty=(stage.clientHeight-H*s)/2; apply(); queueBake();
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
  stage.addEventListener('pointerdown', e=>{{ drag={{x:e.clientX-tx, y:e.clientY-ty}}; gen++;
    stage.setPointerCapture(e.pointerId); }});
  stage.addEventListener('pointermove', e=>{{ if(drag){{
    tx=e.clientX-drag.x; ty=e.clientY-drag.y; apply(); }} }});
  stage.addEventListener('pointerup', ()=>{{ drag=null; queueBake(); }});
  document.querySelectorAll('#panel input').forEach(cb=>cb.addEventListener('change', ()=>{{
    const l=L.find(l=>l.id===cb.dataset.layer); l.on=cb.checked;
    drawOverview();
    if (l.on) paintLayer(l); else place(l);  // one layer, not all
  }}));
</script>
""")
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
