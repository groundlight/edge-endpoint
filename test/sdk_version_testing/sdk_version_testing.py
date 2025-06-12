import os
import shutil
import subprocess
import sys
import tempfile
from typing import List, Tuple

import requests
from packaging.version import parse as parse_version

# This script allows you to test submitting an image query to the edge endpoint across past SDK versions, to ensure that
# changes made are backwards-compatible. Currently this is not run automatically.
# NOTE: this is rough test code and may not work exactly as intended.


def fetch_package_versions(package_name: str) -> List[str]:
    """Fetch all available versions of a package from PyPI."""
    url = f"https://pypi.org/pypi/{package_name}/json"
    response = requests.get(url)
    response.raise_for_status()
    versions = list(response.json()["releases"].keys())
    return sorted(versions, key=parse_version, reverse=True)


def run_test_in_venv(
    package: str, version: str, asset_path: str, endpoint: str, detector_id: str
) -> Tuple[str, bool, str]:
    """Run the Groundlight test in a virtual environment with a specific package version."""
    with tempfile.TemporaryDirectory() as tempdir:
        venv_dir = os.path.join(tempdir, "venv")
        subprocess.run([sys.executable, "-m", "venv", venv_dir], check=True)

        pip_path = os.path.join(venv_dir, "bin", "pip")
        python_path = os.path.join(venv_dir, "bin", "python")

        try:
            subprocess.run(
                [pip_path, "install", f"{package}=={version}"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            subprocess.run(
                [pip_path, "install", "wheel", "setuptools"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )

            asset_file_copy = os.path.join(tempdir, os.path.basename(asset_path))

            # Copy asset image
            with open(asset_path, "rb") as src, open(asset_file_copy, "wb") as dst:
                dst.write(src.read())

            # Create the test script inline
            test_script = f"""from pathlib import Path
from groundlight import Groundlight

gl = Groundlight(endpoint="{endpoint}")

det = "{detector_id}"
iq = gl.submit_image_query(detector=det, image="{asset_file_copy}", wait=0, confidence_threshold=0.5)
print(iq)
"""

            test_file_path = os.path.join(tempdir, "test_script.py")
            with open(test_file_path, "w") as f:
                f.write(test_script)

            result = subprocess.run(
                [python_path, test_file_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
            )
            success = result.returncode == 0
            return (version, success, result.stderr.decode() if not success else result.stdout.decode())
        except subprocess.CalledProcessError as e:
            return (version, False, e.stderr.decode() if e.stderr else "Error occurred")


def main(package: str, asset_path: str, endpoint: str, detector_id: str, max_versions: int = 10):
    """Main function to test package versions."""
    versions = fetch_package_versions(package)
    results = []

    # Create logs directory relative to the script's location
    script_dir = os.path.dirname(os.path.abspath(__file__))
    logs_dir = os.path.join(script_dir, "logs")

    # Remove logs directory if it exists, then create it fresh
    if os.path.exists(logs_dir):
        shutil.rmtree(logs_dir)
    os.makedirs(logs_dir)

    for i, version in enumerate(versions[:max_versions], 1):
        print(f"[{i}/{max_versions}] Testing {package}=={version}...")
        tested_version, success, output = run_test_in_venv(package, version, asset_path, endpoint, detector_id)

        log_path = os.path.join(logs_dir, f"{version}.log")
        with open(log_path, "w") as f:
            f.write(output)

        results.append((tested_version, success, log_path))

    print("\n=== Summary ===")
    for version, success, log_path in results:
        status = "✅ Success" if success else "❌ Failure"
        print(f"{version}: {status} — log: {log_path}")


if __name__ == "__main__":
    if len(sys.argv) != 6:
        print(
            "Usage: python sdk_version_testing.py <package_name> <path_to_image_file> <endpoint> <detector_id> <max_versions>"
        )
        print("Example: python sdk_version_testing.py groundlight cat.jpeg http://10.11.2.33:30101 det_xyz 10")
        sys.exit(1)

    package_name = sys.argv[1]
    asset_path = sys.argv[2]
    endpoint = sys.argv[3]
    detector_id = sys.argv[4]
    max_versions = int(sys.argv[5])
    main(package_name, asset_path, endpoint, detector_id, max_versions)
