# Project Overview

## Title

Predictive Reconstruction of Fragmented LoRa Telemetry

## Elevator Pitch

This project builds a middleware layer between a LoRa gateway and an intelligence dashboard. Instead of waiting for perfect retransmissions, it detects broken telemetry, repairs recoverable structure, predicts missing coordinates from historical movement, and keeps the operational picture moving with clearly marked estimated points.

## Problem Solved

LoRa telemetry can arrive incomplete because of low bitrate, interference, terrain obstruction, or packet corruption. A conventional dashboard discards malformed data and causes track gaps, stuttering movement, and situational blindness. This system reduces those gaps by reconstructing usable telemetry in real time.

## Core Features

- Fragmented JSON detection and header or footer repair
- NMEA checksum verification and malformed sentence handling
- Historical motion buffer per node
- Predictive coordinate estimation using previous position, speed, and heading
- Lightweight Kalman-based smoothing
- Visual distinction between verified and estimated points
- Simple local dashboard and ingestion API for demonstration

## Architecture

1. LoRa gateway sends raw packet strings.
2. Middleware parses JSON or NMEA.
3. Integrity layer flags fragmentation, syntax issues, or checksum mismatches.
4. Reconstruction layer fills missing values using node history.
5. State estimation layer smooths the path.
6. Dashboard receives a normalized payload with confidence and render hints.

## Why This Is Strong for Interviews

- Shows real-time data engineering
- Shows malformed stream recovery
- Shows applied AI and prediction logic
- Shows state estimation with Kalman filtering
- Shows product thinking because estimated data is visually distinguished rather than silently mixed with verified data

## Demo Routes

- `GET /` serves the local dashboard
- `GET /demo-stream` loads a sample packet stream
- `POST /ingest` reconstructs a raw packet and returns a dashboard-ready payload

## Run

```powershell
python app.py
```
