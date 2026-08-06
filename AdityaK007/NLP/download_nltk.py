"""
download_nltk.py
Run once at HF Space build time to pull NLTK models needed by the POS fallback.
Add this to Dockerfile / setup.sh if not using the pip requirements trick.
"""
import nltk
nltk.download('averaged_perceptron_tagger_eng', quiet=True)
nltk.download('punkt', quiet=True)
nltk.download('punkt_tab', quiet=True)
print("NLTK data downloaded.")