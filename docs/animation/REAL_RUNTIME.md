# Real local vision runtime evidence

Run from the repository root:

```bash
PYTHONPATH=apps/api python scripts/generate_real_runtime_evidence.py
```

The generator resets and seeds the local SQLite demonstration database, runs the actual HarborVision motion pipeline against `data/sample/restricted-zone-demo.mp4`, persists the safety event, writes the annotated MP4, and records a per-track CSV trace. The source is repository-generated synthetic smoke media; it is not field footage.

Captured artifacts:

- `runtime-evidence/harborvision-vision-runtime.mp4` — 150 frames, 960×540, 15 FPS;
- `runtime-evidence/harborvision-vision-runtime-poster.jpg` — representative frame from the actual annotated output;
- `runtime-evidence/harborvision-vision-trace.csv` — 149 rows from the executed tracker;
- `runtime-evidence/harborvision-vision-runtime-summary.json` — source hash, runtime metadata, event details, artifact hashes, and limitations.

The executed path is MOG2 foreground subtraction, morphology, contour area filtering, nearest-centroid tracking, polygon membership, and dwell/cooldown event persistence. There is no learned checkpoint or external endpoint. It detects motion-derived tracked objects, not semantic people, vehicles, PPE, or certified safety conditions. OCR remains explicitly blocked when the Tesseract executable is absent from `PATH`.
