"""
CLI entry point for testing the Laya assistant (Stage 1).
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.agent import LayaAgent
from src.utils.config import load_config
from src.utils.logger import setup_logging

from src.tools.registry import ensure_tools_loaded
ensure_tools_loaded()
from src.ui.tray import start_tray_icon
from src.core.mcp import mcp_manager
from src.core.proactive import proactive_engine

def update_ui(ui, state):
    if ui:
        ui.set_state(state)

async def main_loop(use_voice: bool = False, ui=None):
    print("\n" + "="*50)
    print(f"LAYA ASSISTANT — STAGE {'2 (VOICE)' if use_voice else '1 (TEXT)'}")
    if use_voice:
        print("Hold 'Right Ctrl' to speak. Type 'exit' to stop.")
    else:
        print("Type 'exit' or 'quit' to stop.")
    print("="*50 + "\n")
    
    # 1. Setup
    config_path = Path("config/settings.yaml")
    config = load_config(config_path if config_path.exists() else None)
    
    # Configure logging
    log_dir = Path("logs")
    setup_logging(log_dir=log_dir, human_readable=True)
    
    # 2. Initialize Agent
    print("Initializing Laya (downloading model if first run)...")
    agent = LayaAgent(config)
    
    # 2.5 Initialize Voice if requested
    if use_voice:
        print("Initializing Speech Models (this takes a few seconds)...")
        from src.voice.stt import FasterWhisperSTT
        from src.voice.tts import EdgeTTS
        from src.voice.listener import PushToTalkListener
        
        # High performance CUDA/CPU with base.en and beam_size=1 (~35ms latency)
        stt = FasterWhisperSTT(model_size="base.en", device="auto", beam_size=1)
        tts = EdgeTTS()
        def on_start_speaking():
            update_ui(ui, 'listening')
            tts.stop()

        listener = PushToTalkListener(
            hotkey="right ctrl",
            on_listen_start=on_start_speaking,
            on_listen_stop=lambda: update_ui(ui, 'idle')
        )
        listener.start()
        
    # 2.8 Start MCP Client & Proactivity background engines
    asyncio.create_task(mcp_manager.start_all())
    proactive_engine.start()

    print("Ready.\n")
    
    # 3. REPL loop
    update_ui(ui, 'idle')
    try:
        while True:
            try:
                if use_voice:
                    audio = await listener.get_audio_async()
                    if len(audio) == 0:
                        continue
                    update_ui(ui, 'thinking')
                    print("\nTranscribing...", end="\r")
                    user_input = await stt.transcribe(audio)
                    if not user_input:
                        update_ui(ui, 'idle')
                        continue
                    print(f"You (Voice): {user_input}    ")
                else:
                    user_input = input("\nYou: ").strip()
                    if not user_input:
                        continue
                    
                if user_input.lower() in ("exit", "quit", "stop listening"):
                    break
                    
                if not use_voice:
                    print("\nLaya is thinking...")
                
                update_ui(ui, 'working')
                response = await agent.process_request(user_input)
                
                print(f"Laya: {response}")
                if use_voice:
                    update_ui(ui, 'speaking')
                    await tts.speak(response)
                
                update_ui(ui, 'idle')
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                update_ui(ui, 'error')
                print(f"\n[Error] {e}")
    finally:
        proactive_engine.stop()
        await mcp_manager.stop_all()
        if use_voice:
            listener.stop()


def start_bg_loop(use_voice, ui):
    """Run the asyncio loop in a background thread."""
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main_loop(use_voice, ui))
    if ui and ui.app:
        ui.app.quit()

def main():
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    parser = argparse.ArgumentParser(description="Run Laya Assistant")
    parser.add_argument("--voice", action="store_true", help="Enable Push-to-Talk voice mode")
    parser.add_argument("--ui", action="store_true", help="Enable the Desktop UI overlay")
    args = parser.parse_args()

    # Start System Tray presence (escape hatch & settings access)
    tray = start_tray_icon()

    if args.ui:
        from src.ui.window import UIController
        import threading
        
        ui = UIController()
        # Start voice loop in background
        t = threading.Thread(target=start_bg_loop, args=(args.voice, ui), daemon=True)
        t.start()
        # Start UI on main thread (blocks until window closed)
        ui.start_ui()
    else:
        start_bg_loop(args.voice, None)


if __name__ == "__main__":
    main()
