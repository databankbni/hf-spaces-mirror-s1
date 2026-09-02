import os
import subprocess

class ZentraXAutonomousCore:
    def __init__(self, workspace_path: str):
        self.workspace_path = workspace_path

    def write_and_test_code(self, filename: str, code_content: str):
        """
        এআই দ্বারা জেনারেট করা কোড ফাইলে সেভ করে এবং স্যান্ডবক্সে টেস্ট করে
        """
        file_path = os.path.join(self.workspace_path, filename)
        
        try:
            # ১. কোড ফাইল রাইট বা আপডেট করা
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(code_content)
            
            # ২. কোড এক্সিকিউট করে টেস্ট করা (স্যান্ডবক্স টেস্ট)
            result = subprocess.run(
                ["python3", file_path],
                capture_output=True,
                text=True,
                timeout=15
            )
            
            # ৩. ফলাফল যাচাই
            if result.returncode == 0:
                return {
                    "status": "success",
                    "message": "Code executed and verified successfully!",
                    "output": result.stdout
                }
            else:
                return {
                    "status": "error",
                    "message": "Syntax or Runtime error detected.",
                    "stderr": result.stderr
                }
                
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e)
            }

    def self_git_commit_push(self, commit_message: str):
        """
        কোড সফলভাবে টেস্ট হওয়ার পর নিজে থেকেই গিটহাবে পুশ করে দেওয়া
        """
        try:
            subprocess.run(["git", "add", "."], check=True)
            subprocess.run(["git", "commit", "-m", commit_message], check=True)
            subprocess.run(["git", "push", "origin", "main"], check=True)
            return {"status": "success", "message": "Changes pushed to GitHub autonomously!"}
        except subprocess.CalledProcessError as e:
            return {"status": "error", "message": str(e)}
