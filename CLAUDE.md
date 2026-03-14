# TikTok Live Recording Project

## Scripts
- `apps/recorder/src/record_tiktok_live.py` — Graba TikTok live a MPEG-TS (reproducible en VLC en tiempo real)
- `apps/cli/src/transcribe.py` — Transcribe audio a .srt + .txt con faster-whisper
- `apps/cli/src/index_session.py` — Indexa sesiones en SQLite con embeddings (text + audio)
- `apps/cli/src/find_clips.py` — Búsqueda semántica de clips sobre sesiones indexadas

## Herramientas
- ffmpeg: `D:\bin\ffmpeg.exe`
- Python: solo via `uv run` (venv local + pyproject.toml)
- Modelos: `D:\files\models` (SSD)

## Workflow
1. `cd apps/recorder && uv run src/record_tiktok_live.py <username>` → `material/{user}/{date}/live_full.ts`
2. Extraer audio: `ffmpeg -i live_full.ts -vn -acodec libopus -b:a 64k live_audio.opus`
3. `cd apps/cli && uv run src/transcribe.py <audio_file> [model]` → `.srt` + `.txt`
4. `cd apps/cli && uv run src/index_session.py <session_dir> --srt <file.srt>` — indexar sesión
5. `cd apps/cli && uv run src/find_clips.py "<query>"` — buscar clips

## Config
- `.env` — `HF_HUB_CACHE`, `PYTHONIOENCODING`

## Pendiente
- Setup DirectML para transcripción con GPU AMD (RX 6700 XT)

## Design Context

### Users
Single developer exploring clips extracted from TikTok live recordings. The tool is personal, local, used after recording sessions to browse, filter, and discover interesting moments. Context is casual — entertainment content, often late-night sessions.

### Brand Personality
**Playful, bold, expressive.** This is not a corporate dashboard — it's a personal creative tool for entertainment content. The UI should have energy and personality that matches the live-streaming world it serves.

### Aesthetic Direction
- **Visual tone:** Bold and expressive — strong colors, distinctive layouts, personality in typography and interaction. Not generic admin panel.
- **Reference:** StreamElements — streaming-oriented dashboards, colorful, engaging, built for content creators.
- **Anti-references:** Generic AI-generated dashboards (slate + teal, card grids, system-ui font). Stock admin templates. Gray-on-white corporate tools.
- **Theme:** Both light and dark mode (respect OS `prefers-color-scheme`). Dark mode is primary given the late-night usage context.

### Design Principles
1. **Entertainment energy** — The content is fun (TikTok lives, laughter, moments). The UI should reflect that energy, not suppress it with corporate neutrality.
2. **Bold over safe** — Prefer strong color, distinctive typography, and confident layout over the "safe" generic look. Take visual risks.
3. **Dense but clear** — Show lots of data (clips, scores, timecodes) without feeling cluttered. Use hierarchy, color, and spacing to create clarity in density.
4. **Personality in details** — Micro-interactions, playful empty states, distinctive iconography. The small touches matter.
5. **Dark-first** — Design for dark mode first, then adapt for light. Dark suits both the streaming context and late-night usage.
