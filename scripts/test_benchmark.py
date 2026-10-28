import asyncio, time, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.config import load_config
from src.core.agent import LayaAgent

async def run_benchmark():
    config = load_config(Path("config/settings.yaml"))
    agent = LayaAgent(config)
    
    tests = [
        ("pause the music", "Fast Path Media"),
        ("can you open discord", "Fast Path Discord"),
        ("open brave", "Fast Path Brave"),
        ("whats the time in japan rn", "Fast Path Time"),
        ("what is the capital of japan", "System 2 LLM"),
        ("list my github repos", "System 2 GitHub Tool"),
    ]
    
    for cmd, desc in tests:
        t0 = time.perf_counter()
        res = await agent.process_request(cmd)
        dt = (time.perf_counter() - t0) * 1000
        print(f"[{desc}] \"{cmd}\" -> {dt:.1f}ms")
        print(f"   Result: {res}\n")

if __name__ == "__main__":
    asyncio.run(run_benchmark())
