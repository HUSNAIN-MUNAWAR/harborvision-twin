# Public Dataset Demo: World Port Index

## Dataset

| Field | Value |
|---|---|
| Title | World Port Index (Pub 150) |
| Publisher | National Geospatial-Intelligence Agency (NGA) |
| Official source | https://msi.nga.mil/Publications/WPI |
| Machine-readable source used | ArcGIS Feature Service copy of WPI Ports 2017 |
| Query endpoint | https://services2.arcgis.com/jUpNdisbWqRpMo35/arcgis/rest/services/WPI_Ports2017/FeatureServer/0/query |
| License | Public domain; U.S. Government work under 17 U.S.C. §105 |
| Download date | 2026-07-19 |
| Committed file | `data/sample/world-port-index-sample.csv` |

The World Port Index contains locations, physical characteristics, known facilities, and available services for ports and shipping facilities. HarborVision Twin uses a processed sample to demonstrate how public maritime reference data can support smart-port planning screens without implying any live customer deployment.

## Why This Dataset Fits

HarborVision Twin models terminal operations: berths, vessels, yards, gates, safety events, equipment, analytics, and reports. The WPI sample is not used as live terminal telemetry. It is used as public-domain port reference data for comparative planning and for a credible dataset-backed UI/API workflow.

## Reproduction

```bash
python scripts/download_public_dataset.py
```

The script:

1. Queries the public ArcGIS Feature Service.
2. Selects WPI fields relevant to terminal planning and service readiness.
3. Keeps only records with valid identifiers, names, coordinates, country codes, and large/medium harbor size values.
4. Scores each port with a deterministic service-coverage heuristic.
5. Writes the top 120 records to `data/sample/world-port-index-sample.csv`.

The committed CSV is intentionally small so contributors can run the default demo without network access.

## Fields Used

- WPI number.
- Port name and country code.
- Latitude and longitude.
- Harbor size, harbor type, and shelter.
- Tide range, channel-depth code, cargo-depth code, and maximum-vessel code.
- ETA message, pilotage, tug assistance, cargo wharf, VHF, rail, medical, provisions, water, fuel, diesel, repairs, and railway indicators.

## Fields Ignored

The source includes many additional navigational, communications, facilities, and supply fields. HarborVision ignores fields that are not displayed or used by the current public-dataset workflow.

## Transformations

- Blank and `null` source values are normalized to empty strings.
- Numeric identifiers are written without trailing `.0`.
- Only large (`L`) and medium (`M`) harbor records are included.
- A derived `readiness_score` is calculated from service availability indicators and harbor-size hints.
- No personal data is present or processed.

The `readiness_score` is a deterministic demo heuristic, not an official NGA metric and not a safety or navigation recommendation.

## Expected Layout

```text
data/
  sample/
    world-port-index-sample.csv
scripts/
  download_public_dataset.py
docs/
  DATASET.md
```

## Privacy and Ethics

The WPI is public maritime reference data about ports and facilities. It does not contain private customer records, personal data, credentials, medical records, or confidential terminal operating data.

## Limitations

- The processed sample is based on a public ArcGIS Feature Service copy of WPI Ports 2017. Contributors should consult the NGA WPI page for current operational planning.
- The sample supports portfolio/demo workflows only.
- WPI data does not replace local port agents, official charts, Sailing Directions, notices to mariners, berth restrictions, pilots, terminal operating systems, or safety procedures.
- The sample does not prove HarborVision is deployed at, endorsed by, or affiliated with any listed port.
