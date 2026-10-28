import asyncio
import os
import re
import tempfile
import edge_tts
from edge_tts import Communicate
import pygame
import threading
import time

from src.utils.logger import get_logger

logger = get_logger("voice.tts")

# Initialize pygame mixer once for playing MP3s
try:
    if not pygame.mixer.get_init():
        pygame.mixer.init()
except Exception as e:
    logger.warning(f"Pygame mixer init warning: {e}")


def _split_into_sentences(text: str) -> list[str]:
    """Split text into spoken sentence chunks while preserving decimals & abbreviations."""
    t = text.strip()
    if not t:
        return []
    # Protect common decimals (e.g. 22.5) and abbreviations
    t = re.sub(r"(\d+)\.(\d+)", r"\1<DOT>\2", t)
    t = re.sub(
        r"\b(e\.g\.|i\.e\.|vs\.|Mr\.|Mrs\.|Dr\.)",
        lambda m: m.group(0).replace(".", "<DOT>"),
        t,
        flags=re.IGNORECASE,
    )
    # Split on sentence terminals
    parts = re.split(r"(?<=[.!?])\s+", t)
    sentences = [p.replace("<DOT>", ".").strip() for p in parts if p.strip()]
    return sentences if sentences else [t]


class EdgeTTS:
    def __init__(self, voice: str = "en-US-AriaNeural"):
        self.voice = voice
        self._stop_event = threading.Event()

    async def speak(self, text: str):
        """
        Synthesize text to speech using edge-tts with pipelined sentence streaming.
        Sentence 1 starts playing as soon as it is generated (<800ms TTFA),
        while subsequent sentences are prefetched concurrently in the background.
        """
        if not text or not text.strip():
            return

        self._stop_event.clear()
        sentences = _split_into_sentences(text)
        logger.info(f"Speaking ({len(sentences)} sentence chunks): '{text}'")

        if len(sentences) == 1:
            await self._synthesize_and_play_single(sentences[0])
            return

        # Pipelined sentence streaming
        await self._speak_stream_pipeline(sentences)

    async def _synthesize_sentence(self, sentence: str) -> str | None:
        """Synthesize a single sentence to a temporary MP3 file."""
        if self._stop_event.is_set():
            return None
        with tempfile.NamedTemporaryFile(suffix=".mp3", prefix="laya_tts_", delete=False) as f:
            temp_file = f.name
        try:
            communicate = Communicate(sentence, self.voice)
            await communicate.save(temp_file)
            return temp_file
        except Exception as e:
            logger.error(f"TTS Synthesis error for '{sentence[:30]}': {e}")
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass
            return None

    async def _synthesize_and_play_single(self, sentence: str):
        """Synthesize and play a single sentence chunk."""
        temp_file = await self._synthesize_sentence(sentence)
        if not temp_file:
            return
        try:
            if not self._stop_event.is_set():
                await asyncio.to_thread(self._play_audio_sync, temp_file)
        finally:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass

    async def _speak_stream_pipeline(self, sentences: list[str]):
        """Double-buffered streaming: play sentence N while prefetching sentence N+1."""
        # 1. Synthesize first sentence
        current_file = await self._synthesize_sentence(sentences[0])
        if not current_file or self._stop_event.is_set():
            if current_file and os.path.exists(current_file):
                os.remove(current_file)
            return

        for i in range(1, len(sentences)):
            if self._stop_event.is_set():
                if current_file and os.path.exists(current_file):
                    os.remove(current_file)
                return

            # Start prefetching the next sentence in the background
            next_task = asyncio.create_task(self._synthesize_sentence(sentences[i]))

            # Play current sentence now
            try:
                await asyncio.to_thread(self._play_audio_sync, current_file)
            finally:
                if current_file and os.path.exists(current_file):
                    try:
                        os.remove(current_file)
                    except Exception:
                        pass

            if self._stop_event.is_set():
                next_file = await next_task
                if next_file and os.path.exists(next_file):
                    try:
                        os.remove(next_file)
                    except Exception:
                        pass
                return

            # Wait for next sentence prefetch to finish
            current_file = await next_task
            if not current_file:
                break

        # Play the final sentence
        if current_file and not self._stop_event.is_set():
            try:
                await asyncio.to_thread(self._play_audio_sync, current_file)
            finally:
                if os.path.exists(current_file):
                    try:
                        os.remove(current_file)
                    except Exception:
                        pass

    def _play_audio_sync(self, filepath: str):
        """Play audio synchronously using pygame with interrupt checking."""
        try:
            if not os.path.exists(filepath):
                return
            pygame.mixer.music.load(filepath)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                if self._stop_event.is_set():
                    pygame.mixer.music.stop()
                    break
                pygame.time.Clock().tick(20)
        except Exception as e:
            logger.error(f"Audio playback error: {e}")
        finally:
            try:
                pygame.mixer.music.unload()
            except Exception:
                pass

    def stop(self):
        """Instantly stop any currently playing speech (barge-in)."""
        self._stop_event.set()
        if pygame.mixer.get_init():
            try:
                if pygame.mixer.music.get_busy():
                    pygame.mixer.music.stop()
                    pygame.mixer.music.unload()
                    logger.info("Speech interrupted by user.")
            except Exception:
                pass
