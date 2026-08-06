import os
from dotenv import load_dotenv
load_dotenv()
key = os.environ.get("HF_RW_TOKEN")
from huggingface_hub import login, upload_file, HfApi
login(token=key)
api = HfApi()
user = api.whoami()
print(user["name"])
print(user["auth"])
from transformers import AutoModelForSequenceClassification, AutoTokenizer

model = AutoModelForSequenceClassification.from_pretrained("final_model")
tokenizer = AutoTokenizer.from_pretrained("final_model")

model.push_to_hub("lakresi/toxic-comment-moderator")
tokenizer.push_to_hub("lakresi/toxic-comment-moderator")
upload_file(
    path_or_fileobj="final_model/thresholds.json",
    path_in_repo="thresholds.json",
    repo_id="lakresi/toxic-comment-moderator"
)
