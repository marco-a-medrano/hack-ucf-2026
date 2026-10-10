# ParkVision — Parking Garage Dashboard

A React + Vite dashboard for the hackathon parking rover prototype.

## Start

Install Node.js 20+ and run:

```bash
npm install
npm run dev
```

Open the localhost address printed in your terminal (usually http://localhost:5173).

## Demo controls

- Select a parking space to see its details.
- Click **Toggle occupancy (demo)** to mark it occupied or available.
- For occupied spaces, enter a sample plate and choose **Verify**.
- Test plates: `UCF2026` (valid), `EXPIRE9` (expired), `UNKNOWN` (unregistered).
- Watch occupancy counts, availability, activity, and ticket review update.
- **Reset demo** restores initial data.

## Integration notes

Everything is currently simulated and stored only in browser React state; refreshing resets state. No ESP32, camera, server, or real database connection exists yet. The "Rover Connection" indicator intentionally shows Offline.

To integrate the team's backend, replace local state updates with API calls and/or WebSocket events carrying e.g.:

```json
{"spot_id":"A04","occupied":1,"license_plate":"UCF2026","permit_status":"valid"}
```

Use an authorized test environment and mock license plates; potential violations go to a human review queue, not automatic ticket issuance.
