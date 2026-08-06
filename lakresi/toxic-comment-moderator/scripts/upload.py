from transformers import DistilBertTokenizerFast

tokenizer = DistilBertTokenizerFast.from_pretrained("distilbert-base-uncased")
tokenizer.push_to_hub("lakresi/toxic-comment-moderator")
