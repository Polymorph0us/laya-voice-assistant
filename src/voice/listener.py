import asyncio
import queue
import threading
import time
import numpy as np
import sounddevice as sd
import keyboard

from src.utils.logger import get_logger

logger = get_logger("voice.listener")

class PushToTalkListener:
    def __init__(self, hotkey: str = "right ctrl", sample_rate: int = 16000, on_listen_start=None, on_listen_stop=None):
        self.hotkey = hotkey
        self.sample_rate = sample_rate
        self.on_listen_start = on_listen_start
        self.on_listen_stop = on_listen_stop
        self.audio_queue = queue.Queue()
        self.is_listening = False
        self.should_stop = False
        self.listener_thread = None

    def start(self):
        """Start the background listening thread."""
        self.should_stop = False
        self.listener_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.listener_thread.start()
        logger.info(f"Push-to-Talk listener started. Hold [{self.hotkey}] to speak.")

    def stop(self):
        """Stop the background listening thread."""
        self.should_stop = True
        if self.listener_thread:
            self.listener_thread.join(timeout=1.0)
        logger.info("Push-to-Talk listener stopped.")

    def _listen_loop(self):
        """Background loop checking for hotkey press."""
        audio_data = []
        stream = None

        def audio_callback(indata, frames, time_info, status):
            if status:
                logger.warning(f"Audio status: {status}")
            if self.is_listening:
                audio_data.append(indata.copy())

        while not self.should_stop:
            try:
                is_pressed = keyboard.is_pressed(self.hotkey)
            except Exception as e:
                logger.error(f"Keyboard hook error: {e}")
                time.sleep(1)
                continue

            if is_pressed and not self.is_listening:
                # Key just pressed -> start recording
                self.is_listening = True
                audio_data = []
                logger.info("🎤 Listening...")
                if self.on_listen_start:
                    self.on_listen_start()
                
                try:
                    stream = sd.InputStream(
                        samplerate=self.sample_rate, 
                        channels=1, 
                        dtype='float32',
                        callback=audio_callback
                    )
                    stream.start()
                except Exception as e:
                    logger.error(f"Failed to open microphone: {e}")
                    self.is_listening = False
                    time.sleep(0.5)
                    continue

            elif not is_pressed and self.is_listening:
                # Key just released -> stop recording and queue audio
                self.is_listening = False
                logger.info("🔇 Stopped listening.")
                # We do NOT fire on_listen_stop here, because run.py will handle setting it to 'thinking'.
                # This prevents the race condition between UI states.
                
                if stream:
                    stream.stop()
                    stream.close()
                    stream = None

                if audio_data:
                    # Concatenate all chunks into a single 1D numpy array
                    full_audio = np.concatenate(audio_data, axis=0).flatten()
                    
                    # Only queue if we recorded something substantial (>0.3s)
                    if len(full_audio) > self.sample_rate * 0.3:
                        self.audio_queue.put(full_audio)
                    else:
                        logger.debug("Audio too short, discarded.")

            else:
                # Just sleep briefly to avoid high CPU usage
                time.sleep(0.01)

    async def get_audio_async(self) -> np.ndarray:
        """
        Async generator-like method to get the next recorded audio chunk.
        Blocks (yielding to event loop) until audio is available.
        """
        while not self.should_stop:
            try:
                # Non-blocking get with a small timeout
                # to allow asyncio to switch tasks
                audio = self.audio_queue.get_nowait()
                return audio
            except queue.Empty:
                await asyncio.sleep(0.1)
        return np.array([])
