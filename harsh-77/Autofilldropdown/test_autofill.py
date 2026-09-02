import requests
import json

url = "http://127.0.0.1:8000/api/autofill"
payload = {
    "transcript": "This is a UA observation for Apex Engineering Ltd. on August 5th, 2026 for the AlphaCore Systems service at Adani Solar Park Development in Amravati zone Loc 1. The department is Admin and the contractor is Alpha Contractor. The violator is Rajesh Kumar with ID EMP1042. Rajesh was performing Arc Welding without face protection which is a sub-activity under Activity 1. This is a High risk level hazard of Arc Flash with Airborne Dust. The control measure violation is Acid-resistant flooring and spill kit because the worker did not wear the mandatory face protection while welding. The safety rule violated was Area Inspection. The observation is assigned to Ajay Mohod to resolve by August 12th, 2026."
}

try:
    res = requests.post(url, json=payload)
    print("Status:", res.status_code)
    print("Response JSON:")
    print(json.dumps(res.json(), indent=2))
except Exception as e:
    print("Error:", e)
