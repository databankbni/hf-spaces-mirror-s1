import os
from kaggle.api.kaggle_api_extended import KaggleApi

os.environ["KAGGLE_USERNAME"] = "phcnguynhukendykerry"
os.environ["KAGGLE_KEY"] = "a783ab314abae18f4d109589699bd437"

api = KaggleApi()
api.authenticate()

status_resp = api.kernels_status("phcnguynhukendykerry/omnivoice-worker")
print("Status type:", type(status_resp))
for attr in dir(status_resp):
    if not attr.startswith('_'):
        val = getattr(status_resp, attr)
        if not callable(val):
            print(f"  {attr}: {repr(val)}")
