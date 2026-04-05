"""Export pipeline telemetry to a self-contained HTML animation.

Reads pipeline_events from PostgreSQL and generates pipeline_animation.html.

Usage:
    cd apps/cli && uv run src/export_animation.py [--sessions 531,533,536,537,557,579]
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
OUTPUT = REPO_ROOT / "pipeline_animation.html"

sys.path.insert(0, str(REPO_ROOT / "libs"))
from db import get_connection

PHASE_COLORS = {
    "audio_extract": ("#f43f5e", "#e11d48", "Audio Extract"),
    "transcribe": ("#a855f7", "#7c3aed", "Transcribe"),
    "index_session": ("#3b82f6", "#2563eb", "Index Session"),
    "index_chat": ("#06b6d4", "#0891b2", "Index Chat"),
    "summarize": ("#f59e0b", "#d97706", "Summarize"),
    "analyze_topics": ("#10b981", "#059669", "Analyze Topics"),
    "analyze_chat": ("#ec4899", "#db2777", "Analyze Chat"),
}

PHASE_ORDER = list(PHASE_COLORS.keys())


def load_data(session_ids: list[int] | None = None) -> dict:
    conn = get_connection()
    try:
        if session_ids:
            ph = ",".join(["%s"] * len(session_ids))
            rows = conn.execute(f"""
                SELECT pe.session_id, pe.phase, pe.status,
                       pe.elapsed_seconds, pe.input_bytes, pe.output_bytes,
                       pe.record_count, pe.provider, pe.detail, pe.created_at,
                       s.username, CAST(s.duration_seconds/60 AS INT) as dur_min
                FROM pipeline_events pe
                JOIN sessions s ON pe.session_id = s.id
                WHERE pe.status = 'completed' AND pe.session_id IN ({ph})
                ORDER BY pe.session_id, pe.created_at
            """, session_ids).fetchall()
        else:
            rows = conn.execute("""
                SELECT pe.session_id, pe.phase, pe.status,
                       pe.elapsed_seconds, pe.input_bytes, pe.output_bytes,
                       pe.record_count, pe.provider, pe.detail, pe.created_at,
                       s.username, CAST(s.duration_seconds/60 AS INT) as dur_min
                FROM pipeline_events pe
                JOIN sessions s ON pe.session_id = s.id
                WHERE pe.status = 'completed'
                  AND pe.session_id IN (
                      SELECT DISTINCT session_id FROM pipeline_events
                      WHERE phase = 'audio_extract' AND status = 'completed'
                  )
                ORDER BY pe.session_id, pe.created_at
            """).fetchall()

        # Group by session, keeping first completed event per phase
        sessions = {}
        for r in rows:
            sid = r[0]  # session_id
            if sid not in sessions:
                sessions[sid] = {
                    "id": sid, "user": r[10], "dur_min": r[11],  # username, dur_min
                    "phases": {},
                }
            phase = r[1]  # phase
            if phase not in sessions[sid]["phases"]:
                sessions[sid]["phases"][phase] = {
                    "elapsed": round(r[3] or 0, 1),  # elapsed_seconds
                    "in_bytes": r[4] or 0,  # input_bytes
                    "out_bytes": r[5] or 0,  # output_bytes
                    "records": r[6] or 0,  # record_count
                    "provider": r[7] or "",  # provider
                }

        return {"sessions": sorted(sessions.values(), key=lambda s: s["dur_min"])}
    finally:
        conn.close()


def generate_html(data: dict) -> str:
    sessions_json = json.dumps(data["sessions"], indent=2)

    all_phases = set()
    for s in data["sessions"]:
        all_phases.update(s["phases"].keys())
    active_phases = [p for p in PHASE_ORDER if p in all_phases]

    legend_html = "\n".join(
        f'  <div class="legend-item"><div class="legend-dot" style="background:{PHASE_COLORS[p][0]}"></div>{PHASE_COLORS[p][2]}</div>'
        for p in active_phases
    )

    phase_sections = ""
    for p in active_phases:
        c1, c2, label = PHASE_COLORS[p]
        phase_sections += f'  <div class="phase-title" style="color:{c1}; border-left-color:{c1}; background:rgba({int(c1[1:3],16)},{int(c1[3:5],16)},{int(c1[5:7],16)},.06)">{label}</div>\n'
        phase_sections += f'  <div id="rows-{p}"></div>\n'

    # (HTML template is identical to the original — just the data source changed)
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pipeline Animation</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0a0a0f;color:#e0e0e0;font-family:'JetBrains Mono','Fira Code',monospace;overflow-x:hidden}}
.header{{text-align:center;padding:40px 20px 20px}}
.header h1{{font-size:28px;font-weight:700;background:linear-gradient(135deg,#f43f5e,#a855f7,#3b82f6);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.header p{{color:#666;margin-top:8px;font-size:13px}}
.controls{{display:flex;justify-content:center;gap:12px;padding:16px;position:sticky;top:0;background:#0a0a0f;z-index:10}}
.controls button{{background:#1a1a2e;border:1px solid #333;color:#ccc;padding:8px 20px;border-radius:8px;cursor:pointer;font-family:inherit;font-size:13px;transition:all .2s}}
.controls button:hover{{border-color:#a855f7;color:#fff}}
.controls button.active{{background:#a855f7;border-color:#a855f7;color:#fff}}
.stats-bar{{display:flex;justify-content:center;gap:20px;padding:12px 20px;font-size:12px;color:#888;flex-wrap:wrap}}
.stat{{text-align:center;min-width:70px}}
.stat-val{{font-size:18px;font-weight:700;color:#e0e0e0}}
.legend{{display:flex;justify-content:center;gap:16px;padding:12px 20px;flex-wrap:wrap}}
.legend-item{{display:flex;align-items:center;gap:6px;font-size:11px;color:#999}}
.legend-dot{{width:12px;height:12px;border-radius:3px}}
.section{{max-width:1100px;margin:0 auto;padding:0 30px}}
.phase-title{{font-size:14px;font-weight:600;margin:28px 0 14px;padding:8px 16px;border-left:3px solid;border-radius:0 8px 8px 0}}
.g-row{{display:flex;align-items:center;height:30px;margin:3px 0;opacity:0;transform:translateX(-15px);transition:all .4s ease-out}}
.g-row.visible{{opacity:1;transform:translateX(0)}}
.g-label{{width:180px;font-size:10px;color:#888;flex-shrink:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.g-track{{flex:1;position:relative;height:22px;margin-left:8px}}
.g-bar{{position:absolute;height:22px;border-radius:4px;display:flex;align-items:center;padding:0 6px;font-size:9px;font-weight:600;color:rgba(255,255,255,.85);min-width:1px;transition:width 1.2s ease-out;overflow:hidden;white-space:nowrap}}
.ptag{{display:inline-block;padding:1px 5px;border-radius:3px;font-size:8px;font-weight:700;text-transform:uppercase;margin-left:4px}}
.ptag.groq{{background:rgba(244,63,94,.2);color:#f43f5e}}
.ptag.assemblyai{{background:rgba(168,85,247,.2);color:#a855f7}}
.ptag.gemini{{background:rgba(245,158,11,.2);color:#f59e0b}}
.tl-title{{font-size:14px;font-weight:600;margin:36px 0 14px;padding:8px 16px;border-left:3px solid #10b981;border-radius:0 8px 8px 0;color:#10b981;background:rgba(16,185,129,.06)}}
.st-row{{display:flex;align-items:center;height:34px;margin:4px 0;opacity:0;transform:translateX(-15px);transition:all .5s ease-out}}
.st-row.visible{{opacity:1;transform:translateX(0)}}
.st-label{{width:180px;font-size:11px;color:#999;flex-shrink:0}}
.st-label .dur{{color:#555;font-size:9px}}
.st-track{{flex:1;position:relative;height:26px;margin-left:8px;background:rgba(255,255,255,.02);border-radius:4px;overflow:hidden}}
.st-bar{{position:absolute;top:0;height:26px;display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:600;color:rgba(255,255,255,.85);transition:width 1s ease-out;overflow:hidden;white-space:nowrap}}
</style>
</head>
<body>
<div class="header">
  <h1>Pipeline de Procesamiento</h1>
  <p>TikTok Live Recording &mdash; {len(data["sessions"])} sesiones, {len(active_phases)} fases</p>
</div>
<div class="controls">
  <button id="btn-play" class="active">Play</button>
  <button id="btn-pause">Pause</button>
  <button id="btn-reset">Reset</button>
  <button id="btn-speed1">1x</button>
  <button id="btn-speed5" class="active">5x</button>
  <button id="btn-speed20">20x</button>
</div>
<div class="stats-bar" id="stats-bar"></div>
<div class="legend">
{legend_html}
</div>
<div class="section">
{phase_sections}
  <div class="tl-title">Pipeline completo por sesion</div>
  <div id="timeline"></div>
</div>
<div style="height:60px"></div>
<script>
const SESSIONS = {sessions_json};
const PHASES = {json.dumps(active_phases)};
const COLORS = {json.dumps({p: list(PHASE_COLORS[p][:2]) for p in active_phases})};
const fmt=b=>b>1e9?(b/1e9).toFixed(1)+' GB':b>1e6?(b/1e6).toFixed(0)+' MB':(b/1e3).toFixed(0)+' KB';
PHASES.forEach(phase => {{
  const container = document.getElementById('rows-'+phase);
  if (!container) return;
  const items = SESSIONS.filter(s => s.phases[phase]);
  const maxE = Math.max(...items.map(s => s.phases[phase].elapsed), 1);
  items.forEach(s => {{
    const d = s.phases[phase];
    const pct = (d.elapsed / maxE) * 85;
    const [c1,c2] = COLORS[phase];
    const provTag = d.provider ? '<span class="ptag '+d.provider+'">'+d.provider+'</span>' : '';
    let info = d.elapsed.toFixed(0)+'s';
    if (d.in_bytes > 0) info = fmt(d.in_bytes) + ' &rarr; ' + (d.out_bytes > 0 ? fmt(d.out_bytes) : d.records+' recs') + ' &mdash; ' + info;
    else if (d.records > 0) info = d.records + ' records &mdash; ' + info;
    const row = document.createElement('div');
    row.className = 'g-row';
    row.dataset.phase = phase;
    row.innerHTML = '<div class="g-label"><span style="color:#555">#'+s.id+'</span> @'+s.user.slice(0,14)+' '+provTag+'</div>'
      + '<div class="g-track"><div class="g-bar" style="width:0%;background:linear-gradient(90deg,'+c1+','+c2+')" data-target="'+pct+'">'+info+'</div></div>';
    container.appendChild(row);
  }});
}});
const tlC = document.getElementById('timeline');
const maxTotal = Math.max(...SESSIONS.map(s => PHASES.reduce((a,p) => a + (s.phases[p]?.elapsed||0), 0)), 1);
SESSIONS.forEach(s => {{
  const total = PHASES.reduce((a,p) => a + (s.phases[p]?.elapsed||0), 0);
  const row = document.createElement('div');
  row.className = 'st-row';
  let barsHtml = '', left = 0;
  PHASES.forEach(p => {{
    const d = s.phases[p];
    if (!d) return;
    const w = (d.elapsed / maxTotal) * 90;
    const [c1,c2] = COLORS[p];
    barsHtml += '<div class="st-bar" style="left:'+left+'%;width:0%;background:linear-gradient(90deg,'+c1+','+c2+')" data-target="'+w+'">'+(d.elapsed>=1?d.elapsed.toFixed(0)+'s':'')+'</div>';
    left += w;
  }});
  row.innerHTML = '<div class="st-label"><span style="color:#e0e0e0">#'+s.id+'</span> @'+s.user.slice(0,12)+' <span class="dur">'+s.dur_min+'min &rarr; '+total.toFixed(0)+'s</span></div>'
    + '<div class="st-track">'+barsHtml+'</div>';
  tlC.appendChild(row);
}});
const statsBar = document.getElementById('stats-bar');
statsBar.innerHTML = '<div class="stat"><div class="stat-val">'+SESSIONS.length+'</div>sesiones</div>';
PHASES.forEach(p => {{
  const total = SESSIONS.reduce((a,s) => a + (s.phases[p]?.elapsed||0), 0);
  if (total > 0) statsBar.innerHTML += '<div class="stat"><div class="stat-val" id="st-'+p+'">0s</div>'+p.replace('_',' ')+'</div>';
}});
let speed=5, playing=true, af=null, step=0;
const totalSteps=200;
function animate() {{
  if(!playing) return;
  const p = Math.min(step/totalSteps, 1);
  PHASES.forEach((phase, pi) => {{
    const rows = document.querySelectorAll('[data-phase="'+phase+'"]');
    const start = pi / (PHASES.length + 1);
    rows.forEach((row, i) => {{
      if (p > start + i * 0.02) {{
        row.classList.add('visible');
        row.querySelector('.g-bar').style.width = row.querySelector('.g-bar').dataset.target + '%';
      }}
    }});
  }});
  const tlStart = PHASES.length / (PHASES.length + 1);
  document.querySelectorAll('.st-row').forEach((row, i) => {{
    if (p > tlStart + i * 0.02) {{
      row.classList.add('visible');
      row.querySelectorAll('.st-bar').forEach(b => b.style.width = b.dataset.target + '%');
    }}
  }});
  const reveal = Math.min(p * 1.5, 1);
  PHASES.forEach(phase => {{
    const el = document.getElementById('st-'+phase);
    if (el) {{
      const total = SESSIONS.reduce((a,s) => a + (s.phases[phase]?.elapsed||0), 0);
      el.textContent = (total * reveal).toFixed(0) + 's';
    }}
  }});
  step += speed * 0.3;
  if (step <= totalSteps) af = requestAnimationFrame(animate);
}}
document.getElementById('btn-play').onclick=()=>{{playing=true;animate();setA('btn-play')}};
document.getElementById('btn-pause').onclick=()=>{{playing=false;cancelAnimationFrame(af);setA('btn-pause')}};
document.getElementById('btn-reset').onclick=()=>{{step=0;document.querySelectorAll('.g-row,.st-row').forEach(r=>r.classList.remove('visible'));document.querySelectorAll('.g-bar,.st-bar').forEach(b=>b.style.width='0%');playing=true;animate();setA('btn-play')}};
document.getElementById('btn-speed1').onclick=()=>{{speed=1;setS('btn-speed1')}};
document.getElementById('btn-speed5').onclick=()=>{{speed=5;setS('btn-speed5')}};
document.getElementById('btn-speed20').onclick=()=>{{speed=20;setS('btn-speed20')}};
function setA(id){{['btn-play','btn-pause'].forEach(b=>document.getElementById(b).classList.remove('active'));document.getElementById(id).classList.add('active')}}
function setS(id){{['btn-speed1','btn-speed5','btn-speed20'].forEach(b=>document.getElementById(b).classList.remove('active'));document.getElementById(id).classList.add('active')}}
animate();
</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Export pipeline telemetry to HTML animation")
    parser.add_argument("--sessions", help="Comma-separated session IDs (default: auto-detect)")
    args = parser.parse_args()

    session_ids = [int(x) for x in args.sessions.split(",")] if args.sessions else None
    data = load_data(session_ids)

    if not data["sessions"]:
        print("No pipeline events found.")
        return

    html = generate_html(data)
    OUTPUT.write_text(html, encoding="utf-8")
    print(f"Exported {len(data['sessions'])} sessions, {sum(len(s['phases']) for s in data['sessions'])} phase events")
    print(f"Output: {OUTPUT}")


if __name__ == "__main__":
    main()
