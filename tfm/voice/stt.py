"""Speech to text. Input: 16 kHz mono 16-bit PCM. Output: text (may be empty)."""
import json
import re
import urllib.error
import urllib.request
import uuid

from . import audio, state

VOCAB = ("Terraforming Mars. TR, megacredits, M€, steel, titanium, plants, energy, heat, greenery, ocean, city, "
         "temperature, oxygen, Venus, milestone, award, colony, trade fleet, draft, generation, prelude, "
         "corporation, standard project, Tharsis, Hellas, Elysium, Turmoil, delegate.")

# Whisper-family models invent these on near-silence.
HALLUCINATIONS = {
    "", "you", "thank you", "thanks", "thank you very much", "thanks for watching", "thank you for watching",
    "bye", "okay", "uh", "um", "hmm", "mm", "so", "please subscribe", "subtitles by the amara org community",
}


def clean(text):
    text = (text or "").strip()
    if re.sub(r"[^a-z ]+", "", text.lower()).strip() in HALLUCINATIONS:
        return ""
    return text


class OpenAITranscriber:
    name = "openai"

    def __init__(self, cfg):
        self.key = state.openai_key(cfg)
        if not self.key:
            raise RuntimeError("stt=openai needs an API key: set OPENAI_API_KEY or `tfm voice config --openai-key`")
        self.model = cfg["openai_stt_model"]
        self.language = cfg.get("language")

    def transcribe(self, pcm16k, prompt=""):
        boundary = uuid.uuid4().hex
        fields = {"model": self.model, "response_format": "json", "prompt": (prompt + " " + VOCAB).strip()}
        if self.language:
            fields["language"] = self.language
        body = b""
        for k, v in fields.items():
            body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"speech.wav\"\r\n"
                 "Content-Type: audio/wav\r\n\r\n").encode()
        body += audio.wav_bytes(pcm16k) + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            "https://api.openai.com/v1/audio/transcriptions", data=body, method="POST",
            headers={"Authorization": f"Bearer {self.key}",
                     "Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return clean(json.loads(resp.read().decode()).get("text", ""))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"OpenAI transcription failed ({e.code}): {e.read().decode(errors='replace')[:300]}")


class LocalTranscriber:
    """faster-whisper on the CPU. The model downloads on first use (base.en is ~150 MB)."""
    name = "local"

    def __init__(self, cfg):
        try:
            from faster_whisper import WhisperModel
            import numpy
        except ImportError:
            raise RuntimeError("stt=local needs faster-whisper: pip install -e \".[voice-local]\"") from None
        self.np = numpy
        self.model = WhisperModel(cfg["whisper_model"], device="cpu", compute_type="int8")
        self.language = cfg.get("language")

    def transcribe(self, pcm16k, prompt=""):
        samples = self.np.frombuffer(pcm16k, dtype=self.np.int16).astype(self.np.float32) / 32768.0
        segments, _ = self.model.transcribe(samples, language=self.language, beam_size=5,
                                            initial_prompt=(prompt + " " + VOCAB).strip(),
                                            condition_on_previous_text=False)
        return clean(" ".join(s.text.strip() for s in segments if s.no_speech_prob < 0.6))


def make(cfg):
    choice = cfg.get("stt", "auto")
    if choice == "openai":
        return OpenAITranscriber(cfg)
    if choice == "local":
        return LocalTranscriber(cfg)
    if state.openai_key(cfg):
        return OpenAITranscriber(cfg)
    try:
        return LocalTranscriber(cfg)
    except RuntimeError:
        raise RuntimeError("no speech-to-text engine: set OPENAI_API_KEY, or pip install -e \".[voice-local]\" "
                           "for local transcription") from None
