#!/usr/bin/env python3
import subprocess
import sys
import os

def install():
    # Locate requirements.txt relative to this script
    # Source Code:
    #   GitHub: https://github.com/wanqianwin-jpg/aimp.git
    #   Gitee:  https://gitee.com/wanqianwin/aimp.git
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.abspath(os.path.join(script_dir, "..", ".."))
    req_file = os.path.join(root_dir, "requirements.txt")

    if not os.path.exists(req_file):
        print(f"Error: requirements.txt not found at {req_file}")
        sys.exit(1)

    # Check for requirements_minimal.txt if in restricted environment
    minimal_req_file = os.path.join(root_dir, "requirements_minimal.txt")
    if os.environ.get("OPENCLAW_ENV") or os.environ.get("DOCKER_ENV"):
        if os.path.exists(minimal_req_file):
            print(f"Detected container environment. Using minimal dependencies from {minimal_req_file}...")
            req_file = minimal_req_file

    print(f"Installing dependencies from {req_file}...")
    cmd = [sys.executable, "-m", "pip", "install", "-r", req_file]
    
    # Try installing with --user to avoid permission/managed environment issues
    try:
        print("Attempting install with --user...")
        subprocess.check_call(cmd + ["--user"])
        print("Dependencies installed successfully.")
        return
    except subprocess.CalledProcessError:
        print("Install with --user failed. Trying global install (may require sudo or break system packages)...")
    
    # Fallback to global install (or with --break-system-packages if supported/needed)
    try:
        # Check if we are in a managed environment where we might need --break-system-packages
        # This is a bit of a heuristic.
        subprocess.check_call(cmd + ["--break-system-packages"])
        print("Dependencies installed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Failed to install dependencies: {e}")
        print("Please try installing manually or use a virtual environment.")
        sys.exit(1)

if __name__ == "__main__":
    install()
