import os, subprocess, sys, time

CONFIG_PATH = "/Users/qianwan/.aimp/config.yaml"
HUB_PATH = "/Users/qianwan/ai-zoom/aimp/hub_agent.py"
LOG_PATH = "/Users/qianwan/.aimp/hub.log"
PID_PATH = "/Users/qianwan/.aimp/hub.pid"

# Kill old
try:
    with open(PID_PATH, "r") as f:
        pid = f.read().strip()
        os.system(f"kill {pid} 2>/dev/null")
except:
    pass
os.system("pkill -9 -f hub_agent.py")

# Clean
if os.path.exists(LOG_PATH): os.remove(LOG_PATH)

# Start
env = os.environ.copy()
env["HUB_PASSWORD"] = "vaxefnxhckkytmin"
env["DASHSCOPE_API_KEY"] = "sk-53f52ec4226f4317ac87ac3cf1b96c43"
env["PYTHONUNBUFFERED"] = "1"

proc = subprocess.Popen(
    [sys.executable, HUB_PATH, CONFIG_PATH, "10"],
    env=env,
    stdout=open(LOG_PATH, "w"),
    stderr=subprocess.STDOUT
)

with open(PID_PATH, "w") as f:
    f.write(str(proc.pid))

print(f"Hub started with PID {proc.pid}")
