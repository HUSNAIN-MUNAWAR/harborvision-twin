# HarborVision Twin Phase 2 walkthrough

- `harborvision-phase2-walkthrough.mp4` — H.264, 1440×900, 25 FPS, 26.72 seconds.
- `harborvision-phase2-walkthrough.webm` — original Playwright VP8 recording, 1440×900, 25 FPS, 26.72 seconds.

The walkthrough uses the implemented UI and persisted API data. It covers login, command center, digital twin and playback, container and yard inspection, safety evidence, equipment health, incident review, persisted simulation controls, analytics, report preview, and system health.

Record again with:

```bash
PYTHONPATH=apps/api:scripts python scripts/record_walkthrough.py
ffmpeg -i docs/demo/harborvision-phase2-walkthrough.webm \
  -c:v libx264 -crf 24 -pix_fmt yuv420p \
  docs/demo/harborvision-phase2-walkthrough.mp4
```
