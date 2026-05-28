# Risk Register

## Highest risks

### ES-9 multichannel/DC output from Node fails

Impact: high.  
Mitigation: Day 1 CV output gate; test `node-web-audio-api`; fallback to `naudiodon`/PortAudio; document channel map.

### ES-9 full-duplex software audio path is unreliable

Impact: high; this is now the default artistic sound path.  
Mitigation: Day 1 simultaneous audio-in + main-out + 8-CV-output gate; lower sample rate/buffer if needed; fallback to `naudiodon`/PortAudio, Max, or DAW routing; keep hardware bypass via Stereo Line Out 1U or ES-9 internal mixer documented and patchable.

### Mac main mix crashes, clips, or feeds back

Impact: high.  
Mitigation: limiter, conservative gain staging, watchdog, `/api/silence`, physical mixer mute, and no analog patch from ES-9 main outs back into ES-9 inputs unless intentionally tested.

### Agent/LLM in realtime loop adds latency or brittle failure

Impact: high if used in the reflex arc.
Mitigation: keep the realtime bridge deterministic and local; use any agent only as a slow reflective sidecar that writes bounded, expiring heuristic profiles. Missing/malformed/expired profiles must fall back to safe defaults. Never let agent output change channel maps, gain/CV/brightness safety clamps, serial port names, or live code.

### Camera tracking marginal in dim gallery

Impact: high.  
Mitigation: Day 1 dim-room gate; lower confidence threshold; improve lighting/camera angle; tune sector smoothing.

### ESP32 controller electrical fault

Impact: critical.  
Mitigation: correct reverse-polarity design; rail isolation checks; fuse close to source; conservative brightness; thermal checks.

### D1/reverse-polarity part undersized

Impact: high/thermal.  
Mitigation: do not use 1N5822 in full-current path behind 7.5 A fuse for final; use MOSFET ideal diode or properly rated diode/fuse strategy.

## Operational risks

### Mac mini does not arrive or differs from Studio environment

Impact: critical.  
Mitigation: transfer early; run all gates on Mac mini before travel/install; keep Mac Studio-derived docs/scripts reproducible.

### LED strips not on site or have unexpected color order

Impact: high for visual layer.  
Mitigation: artist confirmation before flight; boot color-order test; configurable color order.

### Gallery WiFi unreliable

Impact: medium.  
Mitigation: travel router; local-only network; no internet dependency.

### Rack patch shifts in transit

Impact: medium/high.  
Mitigation: photograph front/back, label cables, carry-on rack, tighten screws, pack spare patch cables.

### Sector calibration wrong for real room

Impact: medium.  
Mitigation: normalized thresholds; on-site walking calibration; admin state view.

### Morph PWA adds fragility

Impact: low/medium.  
Mitigation: keep it optional and tiny; no auth beyond local network; QR fallback; installation works without it.

## Design risks intentionally avoided

- Per-visitor identity binding.
- Registration/session database.
- Browser-only/software-only synth replacing SWN as the main voice.
- CV at audio rate.
- Hard-coded pixel sector thresholds.
- Cloud inference or external services.
- LLM/agent calls in the immediate audio/CV/light response path.
- Whole-rack travel sprawl.

## Kill/fallback modes

- `/api/silence`: ramp CVs, Mac main output, and lights to safe state.
- CV worker disconnect: sector activity decays.
- ESP32 disconnect: sound continues; lights fail safe.
- Audio listener/analyser disconnect: keep safe main output if stable; lights use sector fallback or idle.
- Software audio engine/main output failure: fade/kill software output, use hardware bypass or ES-9 internal mixer if patched.
- ES-9 CV output failure: stop show or pivot to manually animated rack state; do not fake interactivity.
