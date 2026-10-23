"""PCM helpers. Discord audio is 48 kHz, 16-bit little-endian, stereo; speech-to-text wants 16 kHz mono."""
import io
import wave

try:
    # Standard library up to 3.12; on 3.13+ the audioop-lts package (a discord.py dependency) provides it.
    import audioop
except ImportError:  # pragma: no cover
    audioop = None

DISCORD_RATE = 48000
DISCORD_CHANNELS = 2
WIDTH = 2
FRAME_BYTES = DISCORD_RATE // 50 * DISCORD_CHANNELS * WIDTH  # one 20 ms Discord frame = 3840 bytes


def _need():
    if audioop is None:
        raise RuntimeError("audioop is missing: pip install audioop-lts (needed on Python 3.13+)")


def duration(pcm, rate=DISCORD_RATE, channels=DISCORD_CHANNELS):
    return len(pcm) / (rate * channels * WIDTH)


def rms(pcm):
    _need()
    return audioop.rms(pcm, WIDTH) if pcm else 0


def discord_to_speech(pcm):
    """48 kHz stereo -> 16 kHz mono."""
    _need()
    pcm = pcm[: len(pcm) - len(pcm) % (WIDTH * DISCORD_CHANNELS)]
    mono = audioop.tomono(pcm, WIDTH, 0.5, 0.5)
    out, _ = audioop.ratecv(mono, WIDTH, 1, DISCORD_RATE, 16000, None)
    return out


def to_discord(pcm, rate, channels):
    """Any 16-bit PCM -> 48 kHz stereo, padded to whole 20 ms frames."""
    _need()
    if channels == 2:
        pcm = audioop.tomono(pcm, WIDTH, 0.5, 0.5)
    if rate != DISCORD_RATE:
        pcm, _ = audioop.ratecv(pcm, WIDTH, 1, rate, DISCORD_RATE, None)
    stereo = audioop.tostereo(pcm, WIDTH, 1, 1)
    pad = (-len(stereo)) % FRAME_BYTES
    return stereo + b"\x00" * pad


def wav_bytes(pcm, rate=16000, channels=1):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(WIDTH)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def read_wav(data_or_path):
    """Return (pcm, rate, channels) from a 16-bit WAV file or bytes."""
    src = io.BytesIO(data_or_path) if isinstance(data_or_path, (bytes, bytearray)) else data_or_path
    with wave.open(src, "rb") as w:
        if w.getsampwidth() != WIDTH:
            raise RuntimeError(f"expected 16-bit audio, got {8 * w.getsampwidth()}-bit")
        return w.readframes(w.getnframes()), w.getframerate(), w.getnchannels()
