import requests
import time
import random
from flask import Flask
from threading import Thread
import os


# --- سيرفر وهمي مع عرض الـ IP مباشرة على الصفحة ---
app = Flask('')

@app.route('/')
def home():
    try:
        # محاولة جلب الـ IP لعرضه على الصفحة الرئيسية
        current_ip = requests.get('https://api.ipify.org', timeout=5).text
        return f"""
        <html>
            <body style="font-family: sans-serif; text-align: center; padding-top: 50px; background-color: #1a1a1a; color: white;">
                <h1>🚀 Hybrid Bot Status: Running</h1>
                <p style="font-size: 1.2em;">Server IP: <b style="color: #00ff00;">{current_ip}</b></p>
                <p style="color: #888;">Accounts 2-8 are active (Account 1 is Reserved)</p>
                <hr style="width: 50%; border: 0.5px solid #444;">
                <p>Check the logs for detailed message history.</p>
            </body>
        </html>
        """
    except:
        return "Bot System Online - IP detection failed but script is running."

def run():
    app.run(host='0.0.0.0', port=7860)

def keep_alive():
    t = Thread(target=run)
    t.start()


# --- إعدادات الحسابات والبيانات ---

# 1. النظام المنظم (Account 2 فقط حالياً - Account 1 معطل بطلبك)
FIXED_ACCOUNTS = [
    # {
    #     "name": "Account 1",
    #     "token": os.environ.get("TOKEN_1"),
    #     "messages": ["..."] 
    # },
    {
         "name": "Account 2",
         "token": os.environ.get("TOKEN_2"),
         "messages": [
             "[emote:1730752:emojiAngel]"
         ] 
    },
    {
        "name": "Account 6",
        "token": os.environ.get("TOKEN_6"),
        "messages": [
            
            "[emote:1579033:emojiAstonished]"
          #  "تفائل بالغد من عند الله",
          #  "لا اله الا الله وحده لا شريك له له الملك وله الحمد وهو على كل شئ قدير",
           # "لا حول ولا قوة الا بالله",
           # "سبحان الله وبحمده سبحان الله العظيم"
        ]
    }
   
   
]

# 2. النظام العشوائي (من Account 3 إلى 8)
RANDOM_ACCOUNTS = [
    {
         "name": "Account 3",
         "token": os.environ.get("TOKEN_3"),
         "messages": [
             "اللهم اجعلني من الذاكرين الشاكرين",
             "بسم الله الذي لا يضر مع اسمه شيء في الأرض ولا في السماء وهو السميع العليم",
             "اللهم إني أعوذ بك من الهم والحزن والعجز والكسل",
             "اللهم اصلح لي شأني كله ولا تكلني إلى نفسي طرفة عين",
             "حسبي الله لا إله إلا هو عليه توكلت وهو رب العرش العظيم"
         ]
    },
    {
          "name": "Account 4",
          "token": os.environ.get("TOKEN_4"),
          "messages": [
              "سبحان الله وبحمده، سبحان الله العظيم",
              "اللهم اغفر لي وارحمني واهدني وعافني وارزقني",
              "لا إله إلا أنت سبحانك إني كنت من الظالمين",
              "اللهم إنك عفو تحب العفو فاعفُ عني",
              "اللهم إني أسألك الجنة وأعوذ بك من النار"
          ]
    },
     {
         "name": "Account 5",
         "token": os.environ.get("TOKEN5"),
         "messages": [
             "[emote:1730827:emojiSmart]"
         ]
    }
    ,
     {
          "name": "Account 8",
          "token": os.environ.get("TOKEN_8"),
          "messages": [
              "سبحان الله والحمد لله ولا اله الا الله والله اكبر",
              "اللهم اني اسالك رضاك والجنة واعوذ بك من سخطك والنار",
              "استغفر الله واتوب اليه",
              "حسبنا الله لا اله الا هو عليه توكلت وهو رب العرش العظيم"
          ]
    }
    ,
     {
          "name": "Account 7",
          "token": os.environ.get("TOKEN_7"),
          "messages": [
             "[emote:1730759:emojiCool]"
          ]
    }
]


CHANNEL_ID = "5488870"

def send_from_account(account):
    url = f"https://kick.com/api/v2/messages/send/{CHANNEL_ID}"
    headers = {
        "accept": "application/json, text/plain, */*",
        "authorization": f"Bearer {account['token']}",
        "content-type": "application/json",
        "origin": "https://kick.com",
        "referer": "https://kick.com/amirko",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    msg_content = random.choice(account["messages"])
    data = {"content": msg_content, "type": "message"}
    try:
        # إضافة flush=True لكل برنت لضمان ظهورها في اللوجز فوراً
        response = requests.post(url, json=data, headers=headers, timeout=15)
        if response.status_code in [200, 201]:
            print(f"✅ {account['name']}: تم الإرسال ({msg_content[:25]}...)", flush=True)
        else:
            print(f"❌ {account['name']}: فشل! كود {response.status_code}", flush=True)
    except Exception as e:
        print(f"⚠️ {account['name']}: خطأ تقني {e}", flush=True)

def random_worker(account):
    if not account.get('token'):
        return
    print(f"⚙️ تم تفعيل النظام العشوائي لـ {account['name']}", flush=True)
    while True:
        send_from_account(account)
        wait = random.randint(40, 100)
        time.sleep(wait)

# --- التشغيل الأساسي ---
if __name__ == "__main__":
    # فحص الأي بي في اللوجز عند البداية أيضاً
    try:
        init_ip = requests.get('https://api.ipify.org', timeout=5).text
        print(f"🌐 [SERVER INFO] Initial Public IP: {init_ip}", flush=True)
    except:
        pass

    keep_alive()
    
    for acc in RANDOM_ACCOUNTS:
        if acc.get('token'):
            Thread(target=random_worker, args=(acc,)).start()
            time.sleep(5)

    print("🚀 النظام المجمع بدأ العمل...", flush=True)
    while True:
        for acc in FIXED_ACCOUNTS:
            if acc.get('token'):
                send_from_account(acc)
                time.sleep(20) 
        
        wait_fixed = random.randint(50, 170)
        print(f"⏳ استراحة عشوائية للدورة المنظمة: {wait_fixed} ثانية...", flush=True)
        time.sleep(wait_fixed)