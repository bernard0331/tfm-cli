"""Text to speech. Output: 48 kHz stereo 16-bit PCM ready for Discord (no ffmpeg needed)."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request

from . import audio, state

SPOKEN = [
    (r"M€", " megacredits"), (r"\bMC\b", "megacredits"), (r"°C", " degrees"), (r"\bVP\b", "V P"),
    (r"\bTR\b", "T R"), (r"\bvs\.?\b", "versus"), (r"&", " and "), (r"→", " to "),
]


def speakable(text):
    """Strip markdown and expand game shorthand so it reads naturally aloud."""
    text = re.sub(r"`+|\*+|_{2,}|#+\s*|^\s*[-•]\s+", "", text, flags=re.M)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    for pat, rep in SPOKEN:
        text = re.sub(pat, rep, text)
    return re.sub(r"\s+", " ", text).strip()


def sentences(text, min_len=20):
    """Split for pipelined synthesis; tiny fragments stay attached to the previous sentence."""
    parts = []
    for piece in re.split(r"(?<=[.!?])\s+", text):
        if parts and len(parts[-1]) < min_len:
            parts[-1] += " " + piece
        else:
            parts.append(piece)
    return [p for p in parts if p.strip()] or [text]


class SayVoice:
    """macOS `say`. Better voices: System Settings > Accessibility > Spoken Content > System voice > Manage Voices."""
    name = "say"

    def __init__(self, cfg):
        if not shutil.which("say"):
            raise RuntimeError("tts=say needs macOS (the `say` command)")
        self.voice, self.rate = cfg.get("voice"), cfg.get("rate")

    def synth(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            src, out = os.path.join(tmp, "in.txt"), os.path.join(tmp, "out.wav")
            with open(src, "w") as f:
                f.write(text)
            cmd = ["say", "-f", src, "-o", out, "--file-format=WAVE", "--data-format=LEI16@48000"]
            if self.voice:
                cmd += ["-v", self.voice]
            if self.rate:
                cmd += ["-r", str(self.rate)]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                raise RuntimeError(f"say failed: {r.stderr.strip() or r.returncode}")
            pcm, rate, channels = audio.read_wav(out)
        return audio.to_discord(pcm, rate, channels)


class OpenAIVoice:
    name = "openai"

    def __init__(self, cfg):
        self.key = state.openai_key(cfg)
        if not self.key:
            raise RuntimeError("tts=openai needs an API key: set OPENAI_API_KEY or `tfm voice config --openai-key`")
        self.model, self.voice = cfg["openai_tts_model"], cfg.get("voice") or "alloy"

    def synth(self, text):
        body = json.dumps({"model": self.model, "voice": self.voice, "input": text, "response_format": "pcm"})
        req = urllib.request.Request(
            "https://api.openai.com/v1/audio/speech", data=body.encode(), method="POST",
            headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                pcm = resp.read()  # 24 kHz mono 16-bit
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"OpenAI speech failed ({e.code}): {e.read().decode(errors='replace')[:300]}")
        return audio.to_discord(pcm[: len(pcm) - len(pcm) % 2], 24000, 1)


def make(cfg):
    choice = cfg.get("tts", "auto")
    if choice == "say":
        return SayVoice(cfg)
    if choice == "openai":
        return OpenAIVoice(cfg)
    if shutil.which("say"):
        return SayVoice(cfg)
    if state.openai_key(cfg):
        return OpenAIVoice(cfg)
    raise RuntimeError("no text-to-speech engine: use macOS (`say`) or set OPENAI_API_KEY")
