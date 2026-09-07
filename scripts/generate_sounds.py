"""Regenerate Gudfiles' original, synthesized action cues (no sampled audio)."""
from array import array
import math
from pathlib import Path
import random
import sys
import wave


RATE = 24000
TARGET = Path(__file__).resolve().parents[1] / 'omarchy_file_picker/sounds'


def note(t, frequency, decay, amplitude, start=0):
    t -= start
    if t < 0:
        return 0
    attack = min(1, t / .004)
    return amplitude * attack * math.exp(-t / decay) * math.sin(2 * math.pi * frequency * t)


def samples(cue, duration):
    rng = random.Random(42)
    low_noise = 0
    result = array('h')
    for index in range(round(duration * RATE)):
        t = index / RATE
        low_noise = .75 * low_noise + .25 * rng.uniform(-1, 1)
        if cue == 'drop':
            value = note(t, 360, .028, .3) + note(t, 220, .035, .23, .035)
        elif cue == 'trash':
            envelope = math.sin(math.pi * t / duration) ** 2
            rustle = .42 * low_noise * envelope * (.6 + .4 * math.sin(2 * math.pi * 32 * t) ** 2)
            value = rustle + note(t, 170, .025, .13, .14)
        elif cue == 'delete':
            value = note(t, 240, .025, .25) + note(t, 130, .035, .22, .026)
        else:
            value = note(t, 660, .055, .16) + note(t, 990, .065, .14, .07)
            value += note(t, 1320, .028, .025)
        # Smooth endpoints and generous headroom keep these brief cues gentle.
        fade = min(1, max(0, (duration - t) / .015))
        result.append(round(max(-.5, min(.5, value * fade)) * 32767))
    if sys.byteorder != 'little':
        result.byteswap()
    return result.tobytes()


def main():
    TARGET.mkdir(parents=True, exist_ok=True)
    for cue, duration in [('drop', .17), ('trash', .24), ('delete', .18), ('complete', .32)]:
        with wave.open(str(TARGET / f'{cue}.wav'), 'wb') as output:
            output.setparams((1, 2, RATE, 0, 'NONE', 'not compressed'))
            output.writeframes(samples(cue, duration))
        print(f'{cue}: {round(duration * 1000)} ms')


if __name__ == '__main__':
    main()
