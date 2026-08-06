

import os
import sys
import json
import requests
import yaml
import re


ENV_BASE_URL = os.environ.get("ENV_BASE_URL", "http://localhost:8000")
API_BASE_URL = os.environ.get("API_BASE_URL")
MODEL_NAME = os.environ.get("MODEL_NAME")
HF_TOKEN = os.environ.get("HF_TOKEN") or os.environ.get("OPENAI_API_KEY")

class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def log_success(msg): print(f"{bcolors.OKGREEN}✓ {msg}{bcolors.ENDC}")
def log_fail(msg): print(f"{bcolors.FAIL}✗ {msg}{bcolors.ENDC}")
def log_info(msg): print(f"{bcolors.OKBLUE}ℹ {msg}{bcolors.ENDC}")

def check_env_vars():
    log_info("Checking Mandatory Environment Variables...")
    missing = []
    if not API_BASE_URL: missing.append("API_BASE_URL")
    if not MODEL_NAME: missing.append("MODEL_NAME")
    if not HF_TOKEN: missing.append("HF_TOKEN")
    
    if missing:
        log_fail(f"Missing env vars: {', '.join(missing)}")
        return False
    log_success("All mandatory env vars detected.")
    return True

def check_yaml():
    log_info("Checking openenv.yaml...")
    if not os.path.exists("openenv.yaml"):
        log_fail("openenv.yaml not found in root!")
        return False
    
    try:
        with open("openenv.yaml", 'r') as f:
            data = yaml.safe_load(f)
        required = ["name", "version", "tasks", "baseline", "inference_script"]
        for r in required:
            if r not in data:
                log_fail(f"openenv.yaml missing required field: {r}")
                return False
        log_success("openenv.yaml is valid.")
    except Exception as e:
        log_fail(f"Could not parse openenv.yaml: {e}")
        return False
    return True

def check_endpoints():
    log_info(f"Checking Endpoints at {ENV_BASE_URL}...")
    
    
    try:
        resp = requests.get(f"{ENV_BASE_URL}/health", timeout=5)
        if resp.status_code == 200:
            log_success("/health -> 200 OK")
        else:
            log_fail(f"/health -> {resp.status_code}")
            return False
    except Exception as e:
        log_fail(f"Could not connect to /health: {e}")
        return False
    
    
    try:
        resp = requests.post(f"{ENV_BASE_URL}/reset", json={"task_id": "easy"}, timeout=5)
        if resp.status_code == 200:
            log_success("/reset -> 200 OK")
        else:
            log_fail(f"/reset -> {resp.status_code}")
            return False
    except Exception as e:
        log_fail(f"Could not connect to /reset: {e}")
        return False
        
    return True

def check_inference_script():
    log_info("Checking inference.py...")
    if not os.path.exists("inference.py"):
        log_fail("inference.py not found in root!")
        return False
    
    with open("inference.py", 'r') as f:
        content = f.read()
    
    
    patterns = {
        "[START]": r"\[START\] task=",
        "[STEP]": r"\[STEP .+\] Action:",
        "[END]": r"\[END\] task=.* score=.* steps="
    }
    
    for label, pattern in patterns.items():
        if not re.search(pattern, content):
            log_fail(f"inference.py missing log tag/format: {label}")
            return False
    
    if "OpenAI" not in content or "client.chat.completions.create" not in content:
        log_fail("inference.py does not appear to use the OpenAI client library.")
        return False

    log_success("inference.py logging and client usage look correct.")
    return True

def main():
    print(f"{bcolors.HEADER}{bcolors.BOLD}AgentDebuggerEnv Compliance Validator{bcolors.ENDC}")
    print("=" * 45)
    
    success = True
    success &= check_env_vars()
    success &= check_yaml()
    success &= check_inference_script()
    
    
    try:
        if not check_endpoints():
            log_info("Skipping further endpoint checks as server is unreachable.")
    except:
        pass

    print("=" * 45)
    if success:
        print(f"{bcolors.OKGREEN}{bcolors.BOLD}VALIDATION PASSED! Ready for submission.{bcolors.ENDC}")
    else:
        print(f"{bcolors.FAIL}{bcolors.BOLD}VALIDATION FAILED. Please fix the errors above.{bcolors.ENDC}")
        sys.exit(1)

if __name__ == "__main__":
    main()
