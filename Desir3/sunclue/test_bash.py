import os

os.environ["AGENT_WORKSPACE"] = os.path.abspath("./.test_bash")

from tools import bashtool

def test(command):
    print(f"testing {command}")
    output = bashtool.invoke({"command": command, "workdir": "./.test_bash"})
    print(f"bash output:\n {output}")

cmd_list = [
    "echo hello",
    "seq 1 10000",
    "cat /bin/ls",
    "sleep 100",
    "ls /nonexist",
    "python3 -c \"print('x'*100000)\""
]

cmd_list = [
    "sleep 100",
    "ls /nonexist"
]

for cmd in cmd_list:
    test(cmd)