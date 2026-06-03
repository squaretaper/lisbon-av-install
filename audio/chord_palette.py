"""Chord voicing palette for the SWN three-voice layer.

The SWN has three voices listening to V/oct on ES-9 CV outs 1/2/3. The
reflective reviewer picks a `voicing` for each profile; the bridge looks
it up here and resolves to three semitone offsets from root.

Voicings are intentionally bounded and named — the agent picks a named
voicing from `VOICINGS`, the bridge does the math. This keeps the slow
loop's vocabulary musical rather than numeric.

If the profile sets explicit `chord.voice_*_semitones`, those override
the named voicing (escape hatch for the agent to compose its own chord).

All semitone values are offsets from the chord root.
"""
from __future__ import annotations

# Named voicings — three semitone offsets from root, per voice.
# Voicings are chosen to match install canon (red/brutalist): no overly
# bright major chords, no jazzy extensions. Drone, fifth, suspended,
# minor — sustain-friendly chord families that work at low octaves.
VOICINGS: dict[str, tuple[float, float, float]] = {
    # Stone-walls drone. Voices 1+2+3 unison on root. Empty room.
    "grounding": (0.0, 0.0, 0.0),
    # Octave doubling — root + octave + double octave. Slightly warmer
    # than pure unison but still a single pitch class.
    "octave_stack": (0.0, 12.0, 24.0),
    # Open fifth. Spacious, ambiguous mode. Default 1-2 person presence.
    "open_fifth": (0.0, 7.0, 12.0),
    # Open fifth + low octave below. More body, still no third.
    "deep_fifth": (-12.0, 0.0, 7.0),
    # Minor triad (root, minor third, fifth). Pensive, still bodies.
    "minor_triad": (0.0, 3.0, 7.0),
    # Major triad. Used sparingly; brightening crescendos only.
    "major_triad": (0.0, 4.0, 7.0),
    # Suspended fourth. Tension, expectation. Movement crescendo.
    "suspended_fourth": (0.0, 5.0, 7.0),
    # Suspended second. Lighter than sus4, still no third.
    "suspended_second": (0.0, 2.0, 7.0),
    # Quartal stack (root, 4th, b7). Modal, ambiguous, dense w/o major/minor.
    "quartal": (0.0, 5.0, 10.0),
    # Cluster. Three semitones close together. Dense, anxious. Use rarely.
    "cluster_tight": (0.0, 1.0, 2.0),
    # Wide cluster — minor 2nd + tritone. Modernist tension.
    "cluster_wide": (0.0, 1.0, 6.0),
}

ALLOWED_VOICINGS = frozenset(VOICINGS.keys())

# Default root for the install. D2 = 36 semitones above C0.
# Lisbon stone walls resonate well at low D. Agent can override per profile.
DEFAULT_ROOT_SEMITONES = 36.0  # D2

DEFAULT_SMOOTHING_HZ = 0.35   # gentle slew so V/oct changes don't pop
DEFAULT_PITCH_WANDER = 1.0    # multiplier on the bridge's existing pitch_wander


def resolve_chord(profile_chord: dict | None) -> dict:
    """Resolve a profile's chord block to concrete voice offsets.

    Returns a dict with keys:
      root_semitones: float
      voice_offsets: (float, float, float)  semitones from root, per voice
      smoothing_hz: float
      pitch_wander_scale: float
      voicing: str | None  (the named voicing if one was used)

    Missing fields fall back to safe defaults. Out-of-bounds values get
    clamped by the schema layer at write time, not here — this function
    trusts the input was already validated.
    """
    profile_chord = profile_chord or {}
    voicing_name = profile_chord.get("voicing")
    if isinstance(voicing_name, str) and voicing_name in VOICINGS:
        v1, v2, v3 = VOICINGS[voicing_name]
    else:
        voicing_name = None
        # No named voicing → fall back to open_fifth (current bridge default).
        v1, v2, v3 = VOICINGS["open_fifth"]

    # Explicit voice offsets override the named voicing.
    if "voice_1_semitones" in profile_chord:
        try: v1 = float(profile_chord["voice_1_semitones"])
        except (TypeError, ValueError): pass
    if "voice_2_semitones" in profile_chord:
        try: v2 = float(profile_chord["voice_2_semitones"])
        except (TypeError, ValueError): pass
    if "voice_3_semitones" in profile_chord:
        try: v3 = float(profile_chord["voice_3_semitones"])
        except (TypeError, ValueError): pass

    root = float(profile_chord.get("root_semitones", DEFAULT_ROOT_SEMITONES))
    smoothing = float(profile_chord.get("smoothing_hz", DEFAULT_SMOOTHING_HZ))
    pitch_wander = float(profile_chord.get("pitch_wander_scale", DEFAULT_PITCH_WANDER))

    return {
        "root_semitones": root,
        "voice_offsets": (v1, v2, v3),
        "smoothing_hz": smoothing,
        "pitch_wander_scale": pitch_wander,
        "voicing": voicing_name,
    }
