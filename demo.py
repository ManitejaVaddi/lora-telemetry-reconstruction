from __future__ import annotations

import json

from lora_reconstruction import LoRaTelemetryReconstructor, demo_packets


def main() -> None:
    reconstructor = LoRaTelemetryReconstructor()
    for packet in demo_packets():
        payload = reconstructor.ingest(packet)
        print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
