import os
from kaggle.api.kaggle_api_extended import KaggleApi

# Set credentials in environment for KaggleApi to read
os.environ["KAGGLE_USERNAME"] = "phcnguynhukendykerry"
os.environ["KAGGLE_KEY"] = "a783ab314abae18f4d109589699bd437"

api = KaggleApi()
api.authenticate()

def inspect_kernel(slug):
    print(f"\n=== Inspecting {slug} ===")
    
    # Get status
    try:
        status_resp = api.kernels_status(slug)
        print("Status Response:")
        for attr in dir(status_resp):
            if not attr.startswith('_'):
                val = getattr(status_resp, attr)
                if not callable(val):
                    print(f"  {attr}: {val}")
    except Exception as e:
        print(f"Error getting status: {e}")

    # Get metadata
    try:
        # We can try to pull it
        print("Pulling info...")
        # Get kernel metadata info
        from kagglesdk.kernels.types.kernels_api_service import ApiGetKernelRequest
        with api.build_kaggle_client() as kaggle:
            user_name, kernel_slug = slug.split('/')
            request = ApiGetKernelRequest()
            request.user_name = user_name
            request.kernel_slug = kernel_slug
            resp = kaggle.kernels.kernels_api_client.get_kernel(request)
            print("GetKernel Response:")
            for attr in dir(resp):
                if not attr.startswith('_'):
                    val = getattr(resp, attr)
                    if not callable(val):
                        print(f"  {attr}: {val}")
    except Exception as e:
        print(f"Error getting kernel: {e}")

inspect_kernel("phcnguynhukendykerry/omnivoice-worker")
inspect_kernel("phcnguynhukendykerry/omnivoice-gpu-worker")
