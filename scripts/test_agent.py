import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import src.tools.app_tools, src.tools.system_tools
import src.tools.web_tools, src.tools.media_tools
from src.core.agent import LayaAgent
from src.utils.config import load_config

async def main():
    config = load_config(Path("config/settings.yaml"))
    agent = LayaAgent(config)

    tests = [
        "play blinding lights",
        "play coffee by beabadobee",
        "pause the music",
        "skip this track",
        "open a new tab in brave and go to reddit",
        "open brave",
        "give me the latest news",
        "what's the weather in Mumbai",
        "tell me about black holes",
        "lower the volume to 30%",
        "search the web for python asyncio tutorial",
        "get system info",
    ]

    for cmd in tests:
        print(f"\n>>> {cmd}")
        resp = await agent.process_request(cmd)
        print(f"Laya: {resp}")

if __name__ == "__main__":
    asyncio.run(main())
