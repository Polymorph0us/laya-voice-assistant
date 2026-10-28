import os
import sys
from pathlib import Path
import numpy as np
import ctranslate2
from faster_whisper import WhisperModel
from src.utils.logger import get_logger
import asyncio
import time

logger = get_logger("voice.stt")

# Ensure Windows finds cublas64_12.dll if bundled in torch/lib or site-packages
def _setup_cuda_dlls():
    if os.name != "nt":
        return
    try:
        import torch
        torch_lib = Path(torch.__file__).parent / "lib"
        if torch_lib.exists():
            try:
                os.add_dll_directory(str(torch_lib))
            except Exception:
                pass
            os.environ["PATH"] = str(torch_lib) + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass

_setup_cuda_dlls()


class FasterWhisperSTT:
    def __init__(
        self,
        model_size: str = "base.en",
        device: str = "auto",
        compute_type: str = "auto",
        beam_size: int = 1,
    ):
        """
        Initialize the high-performance STT engine.
        Auto-detects CUDA for ultra-low latency (~30-50ms) inference with 0 CPU RAM overhead.
        Falls back to CPU (int8) if CUDA is unavailable.
        """
        self.beam_size = beam_size

        # Resolve device
        if device == "auto":
            cuda_count = ctranslate2.get_cuda_device_count()
            resolved_device = "cuda" if cuda_count > 0 else "cpu"
        else:
            resolved_device = device

        # Resolve compute_type
        if compute_type == "auto":
            resolved_compute = "float16" if resolved_device == "cuda" else "int8"
        else:
            resolved_compute = compute_type

        logger.info(
            f"Loading faster-whisper '{model_size}' on {resolved_device} ({resolved_compute}, beam_size={beam_size})..."
        )
        start = time.perf_counter()
        try:
            self.model = WhisperModel(
                model_size, device=resolved_device, compute_type=resolved_compute
            )
            self.device = resolved_device
        except Exception as e:
            if resolved_device == "cuda":
                logger.warning(f"Failed to load Whisper on CUDA ({e}), falling back to CPU (int8)...")
                self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
                self.device = "cpu"
            else:
                raise e

        # Warmup model with dummy audio
        try:
            dummy_audio = np.zeros(16000, dtype=np.float32)
            list(self.model.transcribe(dummy_audio, beam_size=1)[0])
        except Exception:
            pass

        logger.info(f"Whisper loaded and warmed up in {time.perf_counter() - start:.2f}s ({self.device})")

    async def transcribe(self, audio_data: np.ndarray, sample_rate: int = 16000) -> str:
        """
        Transcribe audio data asynchronously.
        audio_data: float32 numpy array representing the audio.
        """
        if len(audio_data) == 0:
            return ""

        # Run the inference in a worker thread to keep asyncio event loop responsive
        text = await asyncio.to_thread(self._transcribe_sync, audio_data)
        return text.strip()

    def _transcribe_sync(self, audio_data: np.ndarray) -> str:
        """Synchronous transcription using faster-whisper."""
        try:
            t0 = time.perf_counter()
            segments, info = self.model.transcribe(
                audio_data,
                beam_size=self.beam_size,
                language="en",
                condition_on_previous_text=False,
                vad_filter=True,    # Strips silence/noise before inference
                vad_parameters=dict(min_silence_duration_ms=500),
            )
            text = " ".join([segment.text for segment in segments]).strip()
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.debug(f"Transcribed '{text}' in {elapsed_ms:.1f}ms ({self.device})")
            return text
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return ""
