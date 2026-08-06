import requests
import json

url = "https://alexander920627-phishing-detector.hf.space/predict"

payload = {
    "sender_email": "admin@paypal-security.com"
    "content": " [系統警告] 您的帳戶發生異常，請立即點擊連結重設密碼，否則將永久停權。"
}

print("正在發送測試封包至雲端 API...")
response = requests.post(url, json=payload)

if reponse.status_code == 200:
    print("測試成功! API 回傳結果: ")
    print(json.dumps(response.json(), indent=4, ensure_ascii=False))
else:
    print(f" 發生錯誤，狀態碼:{response.status_code}")
    print(response.text)