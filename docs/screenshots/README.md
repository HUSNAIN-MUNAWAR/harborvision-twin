# HarborVision Twin screenshots

These images were captured from the implemented browser console while it was connected to the running FastAPI application and the deterministic NorthStar terminal database. No feature was added to the images after capture.

1. `login-page.png`
2. `command-center.png`
3. `terminal-digital-twin.png`
4. `historical-playback.png`
5. `berth-planning-timeline.png`
6. `yard-overview.png`
7. `yard-block-stack-view.png`
8. `container-movement-history.png`
9. `gate-operations.png`
10. `ocr-review.png`
11. `safety-event-center.png`
12. `safety-event-evidence.png`
13. `equipment-fleet.png`
14. `equipment-anomaly.png`
15. `reefer-monitoring.png`
16. `incident-detail.png`
17. `analytics.png`
18. `report-preview.png`
19. `simulation-control.png`
20. `system-health.png`
21. `audit-log.png`
22. `api-documentation.png`
23. `cli-output.png`

The capture utility supports both a complete run and isolated workers:

```bash
PYTHONPATH=apps/api:scripts python scripts/capture_screenshots.py
PYTHONPATH=apps/api:scripts python scripts/capture_screenshots.py --screen historical-playback.png
```

Set `HARBORVISION_LOCAL_API` when the API is running on a non-default port.

The isolated mode is useful on managed Chromium hosts where graceful browser teardown can be unreliable after bridge-backed asynchronous actions.
