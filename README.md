# Predictive LoRa Telemetry Reconstruction

**[Live Demo](https://lora-telemetry-reconstruction.onrender.com)**

This project is a Python middleware prototype for recovering fragmented LoRa telemetry before it reaches an intelligence dashboard.

## What it does

- Detects broken or partial JSON packets.
- Detects malformed or checksum-failed NMEA sentences.
- Maintains a node-level historical buffer.
- Predicts missing coordinates from prior motion history.
- Blends a constant-velocity motion model with a lightweight 2D Kalman filter.
- Marks reconstructed positions as `estimated` so the dashboard can render them differently from `verified` points.

## Core design

The middleware is built around a single ingestion entry point:

```python
from lora_reconstruction import LoRaTelemetryReconstructor

reconstructor = LoRaTelemetryReconstructor()
payload = reconstructor.ingest(raw_packet)
```

Each returned payload is dashboard-ready and includes:

- `packet_status`: `verified` or `estimated`
- `render_style`: `verified-dot` or `estimated-dot`
- `confidence`: heuristic confidence score
- `notes`: reconstruction and integrity hints

## Files

- `lora_reconstruction.py`: middleware engine
- `demo.py`: runs a sample stream with fragmented packets
- `app.py`: local web server with `/ingest` API and dashboard
- `static/`: frontend demo for visual continuity
- `PROJECT_OVERVIEW.md`: submission-ready explanation

## Run

```powershell
python demo.py
```

## Run the web demo

```powershell
python app.py
```

Then open `http://127.0.0.1:8000`.

## API example

```json
POST /ingest
{
  "packet": "{\"node_id\":\"alpha-1\",\"timestamp\":\"2026-04-18T10:01:00Z\",\"speed_mps\":4.1,\"heading_deg\":90}"
}
```

## How this maps to your problem statement

1. Packet fragmentation detection
   - Broken JSON headers and footers are auto-corrected when possible.
   - NMEA checksum failures and incomplete sentences are flagged.

2. Predictive completion
   - Missing coordinates are estimated using node history, speed, heading, and prior track geometry.

3. Heuristic smoothing
   - A lightweight constant-velocity Kalman filter smooths the predicted track.

4. Visual continuity
   - Estimated points remain visible but are tagged distinctly so operators know they are inferred.

## Example dashboard payload

```json
{
  "node_id": "alpha-1",
  "timestamp": "2026-04-18T10:00:32+00:00",
  "lat": 17.385002,
  "lon": 78.48811,
  "speed_mps": 4.4,
  "heading_deg": 88.0,
  "source": "json",
  "packet_status": "estimated",
  "confidence": 0.72,
  "render_style": "estimated-dot",
  "notes": [
    "Position reconstructed from historical buffer and motion model"
  ],
  "checksum_valid": null
}
```

