from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from reelforge.providers.tts.base import Speech, wav_duration

_SCOPE = "https://cognitiveservices.azure.com/.default"
# A clear, natural multilingual neural voice; override per config/playbook.
_DEFAULT_VOICE = "en-US-AvaMultilingualNeural"

class AzureSpeech:
    """Passwordless Azure neural TTS against an AIServices/Speech account. Returns a wav plus
    per-word boundary timings (which drive synced captions). Auth via an Entra token — no keys.
    `style` (an mstts express-as style, e.g. 'excited'), `rate`, and `pitch` add modulation via SSML
    so the read isn't flat — but the chosen voice must support the style or it is ignored."""

    def __init__(self, resource_id: str, region: str, voice: str = _DEFAULT_VOICE,
                 style: str = "", rate: str = "", pitch: str = "", credential=None):
        self.resource_id = resource_id
        self.region = region
        self.voice = voice
        self.style = style
        self.rate = rate
        self.pitch = pitch
        self._credential = credential

    def _speech_config(self):
        import azure.cognitiveservices.speech as speechsdk
        cred = self._credential
        if cred is None:
            from azure.identity import DefaultAzureCredential
            cred = DefaultAzureCredential()
        token = cred.get_token(_SCOPE).token
        cfg = speechsdk.SpeechConfig(auth_token=f"aad#{self.resource_id}#{token}",
                                     region=self.region)
        cfg.speech_synthesis_voice_name = self.voice
        return cfg

    def _ssml(self, text: str) -> str:
        inner = escape(text)
        if self.rate or self.pitch:
            inner = (f'<prosody rate="{self.rate or "0%"}" pitch="{self.pitch or "0%"}">'
                     f'{inner}</prosody>')
        if self.style:
            inner = f'<mstts:express-as style="{escape(self.style)}">{inner}</mstts:express-as>'
        return (f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
                f'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="en-US">'
                f'<voice name="{escape(self.voice)}">{inner}</voice></speak>')

    def synth(self, text: str, out_path: Path) -> Speech:
        import azure.cognitiveservices.speech as speechsdk
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        audio_cfg = speechsdk.audio.AudioOutputConfig(filename=str(out_path))
        synth = speechsdk.SpeechSynthesizer(speech_config=self._speech_config(),
                                            audio_config=audio_cfg)
        words: list[tuple[str, float, float]] = []
        synth.synthesis_word_boundary.connect(
            lambda e: words.append((e.text, e.audio_offset / 1e7, e.duration.total_seconds())))
        result = synth.speak_ssml_async(self._ssml(text)).get()
        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            detail = getattr(result, "cancellation_details", None)
            raise RuntimeError(
                f"Azure Speech synth failed: {result.reason} "
                f"{getattr(detail, 'error_details', '')}".strip())
        return Speech(audio_path=out_path, words=words, duration=wav_duration(out_path))
