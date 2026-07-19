# Container OCR Pipeline

## Verified local adapter

The default adapter uses OpenCV and Tesseract on CPU. It does not require an external API or model download.

1. Read a validated local image path.
2. Select the configured container-code region.
3. Convert to grayscale.
4. Apply CLAHE contrast enhancement.
5. Apply Gaussian denoising.
6. Apply Otsu thresholding.
7. Run Tesseract with an alphanumeric whitelist.
8. Normalize text and extract ISO 6346-shaped candidates.
9. Compute and verify the ISO 6346 check digit.
10. Rank candidates and mark uncertain jobs for review.
11. Persist original, crop, enhanced image, raw text, candidates, confidence, latency, and final review metadata.

## Evidence

OCR jobs retain paths relative to the repository storage root. Normal APIs expose evidence through the controlled artifact mount; they do not return host absolute paths.

## Human review

The operations console shows source evidence, candidates, validation status, and manual correction controls. Approval records reviewer identity and review time and can be linked to the gate workflow by an integration adapter.

## Evaluation

Run:

```bash
PYTHONPATH=apps/api python scripts/ocr_evaluate.py
```

The script creates deterministic, legally generated images from seeded valid container numbers and records exact match, character accuracy, valid-ID recovery, latency, confidence, and review-required rate in `docs/ocr-evaluation-results.json`.

These synthetic results are a reproducibility check, not a claim of industrial camera accuracy.

## Optional adapters

The service boundary can support EasyOCR, PaddleOCR, or an ONNX model. Optional engines must document model source, license, expected input, CPU cost, and failure behavior. No restricted model weights are included.
