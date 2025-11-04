import os
import sys
import subprocess
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "load-testing" / "single_client_fps_test.py"

def test_single_client_fps_test_binary():
    env = os.environ.copy()
    subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "BINARY"],
        check=True,
        env=env,
    )
    
def test_single_client_fps_test_count():
    env = os.environ.copy()
    subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "COUNT"],
        check=True,
        env=env,
    )
