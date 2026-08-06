import os
from playwright.sync_api import sync_playwright

def generate_session():
    print("===========================================================")
    print("  Outlook Manual Session Generator")
    print("===========================================================")
    print("  1. A Chrome window will pop open.")
    print("  2. Manually log in to the vignesh.bodiga@sarasanalytics.com account.")
    print("  3. Clear any Captchas, 'Setup Complete', or 'Stay Signed In' prompts.")
    print("  4. Wait until you physically see your fully-loaded INBOX.")
    print("  5. Return to this terminal and hit ENTER.")
    print("===========================================================")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        context = browser.new_context()
        page = context.new_page()
        
        page.goto("https://outlook.office.com/mail/")
        
        input("\n[Action Required] I have reached my inbox. Press ENTER to securely save session...")
        
        auth_path = "outlook_auth.json"
        context.storage_state(path=auth_path)
        
        print(f"\nSUCCESS! Your session has been dumped into '{auth_path}'.")
        print("Your Python orchestrator will now completely bypass Microsoft logins!")

if __name__ == "__main__":
    generate_session()
