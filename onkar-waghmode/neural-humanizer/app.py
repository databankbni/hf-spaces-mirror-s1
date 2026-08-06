import gradio as gr
import random
import nltk
import re
import spacy
from nltk.corpus import wordnet, stopwords
from nltk import pos_tag, word_tokenize
from sklearn.metrics.pairwise import cosine_similarity
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
from sentence_transformers import SentenceTransformer,util
import torch
import numpy as np
from typing import List, Dict, Tuple,Optional
from transformers import pipeline
import google.generativeai as genai
import json
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Configure Gemini API Key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)

model = genai.GenerativeModel("gemini-3.5-flash-lite")

# Download NLTK data
print("Downloading NLTK data...")
for data in ['punkt','punkt_tab', 'wordnet', 'averaged_perceptron_tagger', 'stopwords', 'omw-1.4', 'averaged_perceptron_tagger_eng']:
    try:
        nltk.data.find(f'{data}')
    except:
        nltk.download(data, quiet=True)

# Load models globally
print("Loading models...")
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Using device: {device}")

t5_tokenizer = AutoTokenizer.from_pretrained("Vamsi/T5_Paraphrase_Paws")
t5_model = AutoModelForSeq2SeqLM.from_pretrained("Vamsi/T5_Paraphrase_Paws")
t5_model.to(device)

nli_model = SentenceTransformer("cross-encoder/nli-deberta-v3-base")
similarity_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device=device)
nlp = spacy.load("en_core_web_sm")


ai_detector_pipe = pipeline("text-classification", model="Hello-SimpleAI/chatgpt-detector-roberta")

print("Models loaded successfully!")



# ============================================================================
# STAGE 1: PARAPHRASING WITH T5 MODEL
# ============================================================================
def paraphrase_text(text: str, max_length: int = 512, num_beams: int = 4, 
                   temperature: float = 0.7, top_p: float = 0.9,
                   repetition_penalty: float = 1.2, length_penalty: float = 1.0) -> str:
    """Paraphrase text using T5 model"""
    try:
        input_text = f"paraphrase: {text.strip()}"
        inputs = t5_tokenizer(input_text, return_tensors="pt", 
                            max_length=512, truncation=True, padding=True).to(device)
        
        with torch.no_grad():
            outputs = t5_model.generate(
                **inputs,
                max_length=max_length,
                num_beams=num_beams,
                num_return_sequences=1,
                temperature=temperature,
                do_sample=True if temperature > 0 else False,
                top_p=top_p,
                repetition_penalty=repetition_penalty,
                length_penalty=length_penalty,
                early_stopping=True
            )
        
        result = t5_tokenizer.decode(outputs[0], skip_special_tokens=True)
        return result.strip()
    
    except Exception as e:
        return text

def paraphrase_long_text(text: str, max_length: int = 512, num_beams: int = 4, 
                        temperature: float = 0.7, top_p: float = 0.9,
                        repetition_penalty: float = 1.2, length_penalty: float = 1.0) -> str:
    """Handle long texts by breaking them into chunks"""
    sentences = nltk.sent_tokenize(text)
    paraphrased_sentences = []
    current_chunk = ""
    
    for sentence in sentences:
        if len((current_chunk + " " + sentence).split()) > 80:
            if current_chunk:
                paraphrased = paraphrase_text(current_chunk, max_length, num_beams, 
                                             temperature, top_p, repetition_penalty, length_penalty)
                paraphrased_sentences.append(paraphrased)
            current_chunk = sentence
        else:
            current_chunk += " " + sentence if current_chunk else sentence
    
    if current_chunk:
        paraphrased = paraphrase_text(current_chunk, max_length, num_beams, 
                                     temperature, top_p, repetition_penalty, length_penalty)
        paraphrased_sentences.append(paraphrased)
    
    return " ".join(paraphrased_sentences)


# ============================================================================
# CONTEXTUAL SYNONYM REPLACEMENT
# ============================================================================

class ContextualSynonymReplacer:
    def __init__(self, model_name: str = 'all-MiniLM-L6-v2'):
        """Initialize with sentence transformer for contextual similarity"""
        self.model = SentenceTransformer(model_name)
        self.stop_words = set(stopwords.words('english'))
        
    def get_synonyms(self, word: str, pos: str, max_synonyms: int = 5) -> List[str]:
        """Get WordNet synonyms with POS filtering"""
        pos_mapping = {
            'NN': wordnet.NOUN, 'NNS': wordnet.NOUN, 'NNP': wordnet.NOUN, 'NNPS': wordnet.NOUN,
            'VB': wordnet.VERB, 'VBD': wordnet.VERB, 'VBG': wordnet.VERB, 'VBN': wordnet.VERB,
            'VBP': wordnet.VERB, 'VBZ': wordnet.VERB,
            'JJ': wordnet.ADJ, 'JJR': wordnet.ADJ, 'JJS': wordnet.ADJ,
            'RB': wordnet.ADV, 'RBR': wordnet.ADV, 'RBS': wordnet.ADV
        }
        
        wn_pos = pos_mapping.get(pos, wordnet.NOUN)
        synsets = wordnet.synsets(word.lower(), pos=wn_pos)
        
        if not synsets:
            synsets = wordnet.synsets(word.lower())
        
        synonyms = []
        for synset in synsets[:max_synonyms]:
            for lemma in synset.lemmas():
                syn = lemma.name().replace('_', ' ')
                # Only single words, different from original
                if len(syn.split()) == 1 and syn.lower() != word.lower():
                    synonyms.append(syn)
        
        return list(set(synonyms))
    
    def get_contextual_similarity(self, original_sentence: str, 
                                   modified_sentences: List[str]) -> np.ndarray:
        """Calculate semantic similarity between original and modified sentences"""
        all_sentences = [original_sentence] + modified_sentences
        embeddings = self.model.encode(all_sentences)
        
        # Compute similarity between original and all modified versions
        similarities = cosine_similarity([embeddings[0]], embeddings[1:])[0]
        return similarities
    
    def select_best_synonym(self, word: str, synonyms: List[str], 
                           context: str, word_idx: int, 
                           words: List[str]) -> str:
        """Select synonym that maintains contextual meaning"""
        if not synonyms:
            return word
        
        # Create original sentence
        original_sentence = ' '.join(words)
        
        # Create candidate sentences with each synonym
        candidate_sentences = []
        for syn in synonyms:
            modified_words = words.copy()
            modified_words[word_idx] = syn
            candidate_sentences.append(' '.join(modified_words))
        
        # Calculate contextual similarities
        similarities = self.get_contextual_similarity(original_sentence, candidate_sentences)
        
        # Filter synonyms with high similarity (> threshold)
        similarity_threshold = 0.85
        valid_candidates = [
            (syn, sim) for syn, sim in zip(synonyms, similarities) 
            if sim >= similarity_threshold
        ]
        
        if not valid_candidates:
            # If no candidates meet threshold, return original word
            return word
        
        # Return synonym with highest similarity
        best_synonym = max(valid_candidates, key=lambda x: x[1])[0]
        return best_synonym
    
    def synonym_replace(self, text: str, prob: float = 0.3, 
                       min_word_length: int = 3, 
                       max_synonyms: int = 5) -> str:
        """Replace words with contextually appropriate synonyms"""
        words = word_tokenize(text)
        pos_tags = pos_tag(words)
        new_words = words.copy()
        
        for idx, (word, pos) in enumerate(pos_tags):
            # Skip non-alphabetic tokens
            if not word.isalpha():
                continue
            
            # Skip stopwords and short words
            if word.lower() in self.stop_words or len(word) <= min_word_length:
                continue
            
            # Random probability check
            if random.random() > prob:
                continue
            
            # Get candidate synonyms
            synonyms = self.get_synonyms(word, pos, max_synonyms)
            
            if synonyms:
                # Select best contextual synonym
                best_syn = self.select_best_synonym(
                    word, synonyms, text, idx, words
                )
                new_words[idx] = best_syn
        
        return ' '.join(new_words)


# ============================================================================
# IMPROVED ACADEMIC DISCOURSE TRANSFORMATION
# ============================================================================

class AcademicDiscourseTransformer:
    def __init__(self):
        self.contractions = {
            "don't": "do not", "doesn't": "does not", "didn't": "did not",
            "can't": "cannot", "couldn't": "could not", "shouldn't": "should not",
            "wouldn't": "would not", "won't": "will not", "aren't": "are not",
            "isn't": "is not", "wasn't": "was not", "weren't": "were not",
            "haven't": "have not", "hasn't": "has not", "hadn't": "had not",
            "I'm": "I am", "I've": "I have", "I'll": "I will", "I'd": "I would",
            "you're": "you are", "you've": "you have", "you'll": "you will",
            "we're": "we are", "we've": "we have", "we'll": "we will",
            "they're": "they are", "they've": "they have", "they'll": "they will",
            "it's": "it is", "that's": "that is", "there's": "there is", 
            "what's": "what is"
        }
        
        self.hedges = [
            "it appears that", "it is possible that", "the results suggest",
            "it seems that", "there is evidence that", "it may be the case that",
            "to some extent", "in general terms", "one could argue that",
            "arguably", "potentially"
        ]
        
        self.boosters = [
            "clearly", "indeed", "in fact", "undoubtedly",
            "without doubt", "it is evident that", "there is no question that",
            "certainly", "definitely", "obviously"
        ]
        
        self.connectors = {
            "contrast": ["however", "on the other hand", "in contrast", 
                        "nevertheless", "nonetheless", "conversely"],
            "addition": ["moreover", "furthermore", "in addition", "additionally",
                        "what is more", "besides"],
            "cause_effect": ["therefore", "thus", "as a result", "consequently", 
                           "hence", "accordingly"],
            "example": ["for instance", "for example", "to illustrate", "namely"],
            "emphasis": ["notably", "particularly", "especially", "significantly"],
            "conclusion": ["in conclusion", "overall", "in summary", "to sum up",
                         "in brief"]
        }
        
        self.sentence_starters = [
            "It is important to note that",
            "A key implication is that",
            "The evidence indicates that",
            "The findings suggest that",
            "This demonstrates that",
            "It should be emphasized that",
            "From these observations, it follows that",
            "It is worth noting that"
        ]
        
        # Sentence classification patterns
        self.claim_patterns = [
            r'\b(introduce|present|propose|develop|create|build|design)\b',
            r'\b(this (paper|study|work|research))\b',
            r'\b(we (introduce|present|propose|develop))\b'
        ]
        
        self.evidence_patterns = [
            r'\b(results? (show|indicate|demonstrate|reveal))\b',
            r'\b(findings? (suggest|indicate|show))\b',
            r'\b(data (show|indicate|demonstrate))\b',
            r'\b(experiments? (show|demonstrate|reveal))\b',
            r'\b(analysis (shows?|indicates?|demonstrates?))\b'
        ]
        
        self.interpretation_patterns = [
            r'\b(implies? that|suggests? that|indicates? that)\b',
            r'\b(can be (interpreted|understood|seen))\b',
            r'\b(may (be|indicate|suggest))\b'
        ]
    
    def classify_sentence(self, sentence: str) -> str:
        """Classify sentence by its academic function"""
        sent_lower = sentence.lower()
        
        # Check for claims/contributions
        if any(re.search(pattern, sent_lower) for pattern in self.claim_patterns):
            return 'claim'
        
        # Check for evidence/results
        if any(re.search(pattern, sent_lower) for pattern in self.evidence_patterns):
            return 'evidence'
        
        # Check for interpretations
        if any(re.search(pattern, sent_lower) for pattern in self.interpretation_patterns):
            return 'interpretation'
        
        return 'general'
    
    def detect_semantic_relationship(self, prev_sent: str, curr_sent: str) -> Optional[str]:
        """Detect semantic relationship between consecutive sentences"""
        prev_lower = prev_sent.lower()
        curr_lower = curr_sent.lower()
        
        # Contrast indicators
        contrast_words = ['however', 'but', 'although', 'while', 'whereas', 'despite']
        if any(word in curr_lower for word in contrast_words):
            return 'contrast'
        
        # Addition/continuation indicators
        addition_words = ['also', 'additionally', 'moreover', 'furthermore']
        if any(word in curr_lower for word in addition_words):
            return 'addition'
        
        # Cause-effect indicators
        causal_words = ['therefore', 'thus', 'consequently', 'as a result', 'because']
        if any(word in curr_lower for word in causal_words):
            return 'cause_effect'
        
        # Example indicators
        example_words = ['for example', 'for instance', 'such as', 'including']
        if any(word in curr_lower for word in example_words):
            return 'example'
        
        # Check for negative/positive sentiment shift (basic heuristic)
        negative_words = ['not', 'no', 'never', 'without', 'lacking', 'failed', 'limitation']
        positive_words = ['successful', 'effective', 'improved', 'enhanced', 'benefit']
        
        prev_negative = any(word in prev_lower for word in negative_words)
        curr_negative = any(word in curr_lower for word in negative_words)
        
        if prev_negative != curr_negative:
            return 'contrast'
        
        return None
    
    def expand_contractions(self, text: str) -> str:
        """Expand contractions to formal academic language"""
        for contraction, expansion in self.contractions.items():
            pattern = re.compile(r'\b' + re.escape(contraction) + r'\b', re.IGNORECASE)
            text = pattern.sub(expansion, text)
        return text
    
    def apply_transformation(self, sentence: str, transform_type: str, 
                           connector_type: Optional[str] = None) -> str:
        """Apply a single transformation to a sentence"""
        # Ensure sentence starts with capital letter
        if not sentence[0].isupper():
            sentence = sentence[0].upper() + sentence[1:]
        
        if transform_type == 'hedge':
            hedge = random.choice(self.hedges)
            # Insert hedge after first word or phrase
            return f"{hedge.capitalize()}, {sentence[0].lower() + sentence[1:]}"
        
        elif transform_type == 'booster':
            booster = random.choice(self.boosters)
            return f"{booster.capitalize()}, {sentence}"
        
        elif transform_type == 'starter':
            starter = random.choice(self.sentence_starters)
            return f"{starter} {sentence[0].lower() + sentence[1:]}"
        
        elif transform_type == 'connector' and connector_type:
            connector = random.choice(self.connectors[connector_type])
            return f"{connector.capitalize()}, {sentence[0].lower() + sentence[1:]}"
        
        return sentence
    
    def add_academic_discourse(self, text: str, 
                              transformation_prob: float = 0.3) -> str:
        """
        Add academic discourse markers with context awareness
        
        Args:
            text: Input text
            transformation_prob: Overall probability of transforming a sentence
        """
        # Expand contractions first
        text = self.expand_contractions(text)
        
        # Split into sentences
        sentences = nltk.sent_tokenize(text)
        modified_sentences = []
        
        for i, sent in enumerate(sentences):
            # Classify sentence
            sent_type = self.classify_sentence(sent)
            
            # Determine if transformation should be applied
            if random.random() > transformation_prob:
                modified_sentences.append(sent)
                continue
            
            # Choose transformation based on sentence type and position
            transform_type = None
            connector_type = None
            
            if i == 0:
                # First sentence: avoid connectors
                if sent_type == 'claim':
                    transform_type = random.choice(['booster', 'starter', None])
                else:
                    transform_type = random.choice(['starter', None])
            
            else:
                # Get previous sentence for context
                prev_sent = sentences[i-1]
                relationship = self.detect_semantic_relationship(prev_sent, sent)
                
                if relationship:
                    # Use appropriate connector
                    transform_type = 'connector'
                    connector_type = relationship
                
                elif sent_type == 'claim':
                    # Claims: prefer boosters or starters
                    transform_type = random.choice(['booster', 'starter', None])
                
                elif sent_type == 'evidence':
                    # Evidence: avoid hedges (data should be certain)
                    transform_type = random.choice(['booster', None])
                
                elif sent_type == 'interpretation':
                    # Interpretations: can use hedges
                    transform_type = random.choice(['hedge', 'starter', None])
                
                else:
                    # General sentences: balanced approach
                    transform_type = random.choice([
                        'hedge', 'booster', 'starter', 'connector', None
                    ])
                    if transform_type == 'connector':
                        connector_type = random.choice(list(self.connectors.keys()))
            
            # Apply transformation
            if transform_type:
                sent = self.apply_transformation(sent, transform_type, connector_type)
            
            modified_sentences.append(sent)
        
        return ' '.join(modified_sentences)


# ============================================================================
# STAGE 4: SENTENCE STRUCTURE VARIATION
# ============================================================================
def vary_sentence_structure(
    text: str,
    split_prob: float = 0.4,
    merge_prob: float = 0.3,
    min_split_length: int = 20,
    max_merge_length: int = 10
) -> str:
    """
    Enhance sentence structure variation using NLI inference +
    semantic similarity to preserve academic integrity.
    """

    connectors = {
        "contrast": ["however", "nevertheless", "nonetheless", "in contrast"],
        "addition": ["moreover", "furthermore", "in addition", "what is more", "also"],
        "cause_effect": ["therefore", "thus", "consequently", "as a result"],
        "example": ["for example", "for instance", "to illustrate"],
        "conclusion": ["in conclusion", "overall", "in summary"]
    }

    all_connectors = {c.lower() for group in connectors.values() for c in group}

    def already_has_connector(s: str) -> bool:
        s = s.strip().lower()
        return any(s.startswith(c) for c in all_connectors)

    def sentence_is_fragment(s: str) -> bool:
        doc = nlp(s)
        has_verb = any(t.pos_ in ("VERB", "AUX") for t in doc)
        has_subj = any(t.dep_ in ("nsubj", "nsubjpass") for t in doc)
        return not (has_verb and has_subj)

    def choose_connector_type(prev_sent: str, curr_sent: str) -> str:
        curr_lower = curr_sent.lower()

        # Rule-based first
        if any(x in curr_lower for x in ["such as", "for instance", "including"]):
            return "example"
        if curr_lower.startswith(("however", "although", "but", "nevertheless")):
            return "contrast"
        if any(x in curr_lower for x in ["therefore", "thus", "as a result", "because"]):
            return "cause_effect"

        # === NLI inference ===
        try:
            logits = nli_model.predict([(prev_sent, curr_sent)])[0]
            contradiction, neutral, entailment = logits

            if contradiction > 0.40:
                return "contrast"
            if entailment > 0.40:
                if "because" in curr_lower:
                    return "cause_effect"
                return "addition"
        except:
            pass  # fail safe

        # === Similarity fallback ===
        emb = similarity_model.encode([prev_sent, curr_sent], convert_to_tensor=True)
        sim = util.cos_sim(emb[0], emb[1]).item()

        return "addition" if sim >= 0.55 else "contrast"

    def add_connector(prev, curr):
        ctype = choose_connector_type(prev, curr)
        connector = random.choice(connectors[ctype])
        return f"{connector.capitalize()}, {curr[0].lower() + curr[1:]}"

    doc = nlp(text)
    doc_sents = list(doc.sents)  # real spaCy sentence spans
    modified = []

    for idx, sent_span in enumerate(doc_sents):
        sent = sent_span.text.strip()
        words = sent.split()
    
        # SPLIT
        if len(words) > min_split_length and random.random() < split_prob:
            tokens = list(sent_span)  # tokens inside this sentence span
    
            # find split points inside sentence (no sentence-start confusion)
            split_positions = [
                j for j, tok in enumerate(tokens)
                if tok.dep_ in ("cc", "mark")     # coordinating conj / subordinate clause marker
            ]

            
            if split_positions:
                sp = random.choice(split_positions)
                tokens = list(nlp(sent))
                if 0 < sp < len(tokens):
                    first = " ".join(t.text for t in tokens[:sp]).strip()
                    second = " ".join(t.text for t in tokens[sp+1:]).strip()

                    if first and second and not sentence_is_fragment(second):
                        if not already_has_connector(second) and random.random() < 0.5:
                            second = add_connector(first, second)
                        modified.extend([first + ".", second])
                        continue

        # MERGE
        if (modified
            and len(words) < max_merge_length
            and len(modified[-1].split()) < max_merge_length
            and random.random() < merge_prob):

            prev = modified[-1]
            if not already_has_connector(sent):
                merged_clause = add_connector(prev, sent)

                if prev.endswith("."):
                    merged = prev[:-1] + f"; {merged_clause[0].lower() + merged_clause[1:]}"
                else:
                    merged = prev + f", {merged_clause.lower()}"

                if not sentence_is_fragment(sent):
                    modified[-1] = merged
                    continue

        modified.append(sent)

    # Clean + Capitalize sentences
    out = " ".join(modified)
    out = re.sub(r"\s+", " ", out).strip()
    out = ". ".join(s.strip().capitalize() for s in out.split(".") if s.strip()) + "."

    return out


# ============================================================================
# LLM Refinement with Gemini
# ============================================================================

GEMINI_VALIDATION_PROMPT = """
You will be given two texts: an 'Original' text and a 'Transformed' text. The 'Transformed' text is a poor modification of the 'Original', containing grammatical errors, misspellings, and inappropriate synonyms.

Your task is to:

1. Compare the 'Transformed' text word-by-word against the 'Original' text.
2. Identify every word in the 'Transformed' text that is incorrect or a poor substitute.
3. Categorize these into:
   - "irrelevant_incorrect"
   - "inappropriate_synonyms"
4. For each, return a JSON dictionary with
   "transformed_word" : "correct_word_from_original"

### Output Format ###
{
  "irrelevant_incorrect": { "bad_word": "correct_word", ... },
  "inappropriate_synonyms": { "bad_word": "correct_word", ... }
}

### Text ###
Original:
<<<ORIGINAL_TEXT>>>

Transformed:
<<<TRANSFORMED_TEXT>>>
"""

def validateText(original,transformed):
    # ------------------- Build Prompt -------------------
    prompt = GEMINI_VALIDATION_PROMPT \
        .replace("<<<ORIGINAL_TEXT>>>", original) \
        .replace("<<<TRANSFORMED_TEXT>>>", transformed)
    
    # ------------------- Query Gemini -------------------
    response = model.generate_content(prompt)
    result = response.text
    
    try:
        corrections = json.loads(result)
    except:
        # sometimes model adds markdown, brackets etc. optional cleaning
        cleaned = re.sub(r"```json|```", "", result).strip()
        corrections = json.loads(cleaned)
    
    irrelevant = corrections.get("irrelevant_incorrect", {})
    synonyms = corrections.get("inappropriate_synonyms", {})
    
    # ------------------- Update Transformed Text -------------------
    updated_text = transformed
    
    for wrong, right in {**irrelevant, **synonyms}.items():
        updated_text = re.sub(rf"\b{wrong}\b", right, updated_text)
    
    return updated_text

# ============================================================================
# QUALITY CHECK
# ============================================================================
def calculate_similarity(text1: str, text2: str) -> float:
    """Calculate semantic similarity between two texts"""
    try:
        embeddings = similarity_model.encode([text1.strip(), text2.strip()])
        similarity = float(np.dot(embeddings[0], embeddings[1]) / (
            np.linalg.norm(embeddings[0]) * np.linalg.norm(embeddings[1])
        ))
        similarity = round(similarity*100, 2)
        return similarity
    except Exception as e:
        return 0.0


# ============================================================================
# AI Detection
# ============================================================================
def predict_ai_content(text):
    if not text or not text.strip():
        return "No input provided", 0.0

    try:
        result = ai_detector_pipe(text)
        if isinstance(result, list) and len(result) > 0:
            res = result[0]
            ai_content_label = res.get('label', 'Unknown')
            ai_content_score = round(float(res.get('score', 0)) * 100, 2)
            return ai_content_label, ai_content_score
        else:
            return "Invalid response", 0.0
    except Exception as e:
        print(f"Error in prediction: {e}")
        return "Error", 0.0


# ============================================================================
# MAIN HUMANIZER FUNCTION
# ============================================================================
def humanize_text(
    input_text: str,
    # Stage toggles
    enable_stage1: bool,
    enable_stage2: bool,
    enable_stage3: bool,
    enable_stage4: bool,
    # Stage 1 parameters
    temperature: float,
    top_p: float,
    num_beams: int,
    max_length: int,
    repetition_penalty: float,
    length_penalty: float,
    # Stage 2 parameters
    synonym_prob: float,
    min_word_length: int,
    max_synonyms: int,
    # Stage 3 parameters
    hedge_prob: float,
    booster_prob: float,
    connector_prob: float,
    starter_prob: float,
    # Stage 4 parameters
    split_prob: float,
    merge_prob: float,
    min_split_length: int,
    max_merge_length: int
):
    """Main humanizer function that processes text through all enabled stages"""

    print("Text humanization initiated...")
    
    original = input_text
     
    if not input_text.strip():
        return "", 0.0, "Please enter some text to humanize."
    
    try:
        result = input_text
        stages_applied = []
        
        # Stage 1: Paraphrasing
        if enable_stage1:
            word_count = len(result.split())
            if word_count > 100:
                result = paraphrase_long_text(result, max_length, num_beams, temperature, 
                                             top_p, repetition_penalty, length_penalty)
            else:
                result = paraphrase_text(result, max_length, num_beams, temperature, 
                                        top_p, repetition_penalty, length_penalty)
            stages_applied.append("Paraphrasing")
        
        # Stage 2: Synonym Replacement
        if enable_stage2:
            replacer = ContextualSynonymReplacer()
            random.seed(42)  # For reproducibility
            result = replacer.synonym_replace(
                result, 
                prob=0.3, 
                min_word_length=3,
                max_synonyms=5
            )
            stages_applied.append("Synonym Replacement")
        
        # Stage 3: Academic Discourse
        if enable_stage3:
            transformer = AcademicDiscourseTransformer()
            random.seed(42)
            result = transformer.add_academic_discourse(result, transformation_prob=0.4)
            stages_applied.append("Academic Discourse")
        
        # Stage 4: Sentence Structure
        if enable_stage4:
            result = vary_sentence_structure(result, split_prob, merge_prob, 
                                            min_split_length, max_merge_length)
            stages_applied.append("Sentence Structure")
        
        
        # LLM Review
        result = validateText(original,result)
        stages_applied.append("LLM Review")
        
        # Calculate similarity
        similarity = calculate_similarity(input_text, result)
        ai_content_label_generated, ai_content_score_generated = predict_ai_content(result)
        ai_content_label_input, ai_content_score_input = predict_ai_content(input_text)
        
        # Generate status message
        if not stages_applied:
            status = "⚠️ No stages enabled. Please enable at least one stage."
        else:
            status = f"✅ Successfully applied: {', '.join(stages_applied)}"

        print("Text humanization successfully Completed...")
        return result, similarity, status,ai_content_label_generated, ai_content_score_generated,ai_content_label_input, ai_content_score_input
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return "", 0.0, f"❌ Error: {str(e)}"

# ============================================================================
# GRADIO INTERFACE
# ============================================================================
def create_gradio_interface():
    """Create the Gradio interface"""
    
    with gr.Blocks(theme=gr.themes.Soft(), title="Neural Humanizer") as demo:
        gr.Markdown(
            """
            # ✍️ Neural Humanizer
            Transform AI-generated text into natural, human-like language with precision, style, and control.
            """
        )
        
        with gr.Row():
            with gr.Column(scale=2):
                input_text = gr.Textbox(
                    label="Input Text",
                    placeholder="Enter your text here to humanize...",
                    lines=10
                )
                
                with gr.Row():
                    submit_btn = gr.Button("🚀 Transform Text", variant="primary", size="lg")
                    clear_btn = gr.Button("🔄 Clear", size="lg")
                 
                
                output_text = gr.Textbox(
                    label="Humanized Output",
                    lines=10,
                    interactive=False
                )
                
                with gr.Row():
                    gr.Markdown("### Semantic Similarity & Status")
                
                with gr.Row():
                    similarity_output = gr.Number(label="Content Similarity (%)", precision=2)
                    status_output = gr.Textbox(label="Status",interactive=False,lines=2, max_lines=10)
                
                with gr.Row():
                    gr.Markdown("### Given Input Text Analysis")

                with gr.Row():
                        ai_content_label_input = gr.Textbox(
                            label="Detected Content Type",
                            interactive=False,
                            lines=2,
                            max_lines=10
                        )
                        ai_content_score_input = gr.Number(
                            label="Model Confidence (%)",
                            precision=2,
                            interactive=False
                        )

                with gr.Row():
                    gr.Markdown("### Humanized Text Analysis")

                with gr.Row():
                    ai_content_label_generated = gr.Textbox(
                        label="Detected Content Type",
                        interactive=False,
                        lines=2,
                        max_lines=10
                    )
                
                    ai_content_score_generated = gr.Number(
                        label="Model Confidence (%)",
                        precision=2,
                        interactive=False
                    )
                    

    
            with gr.Column(scale=1):
                gr.Markdown("## 🎛️ Pipeline Configuration")
                
                with gr.Accordion("Stage Selection", open=True):
                    enable_stage1 = gr.Checkbox(label="Stage 1: Paraphrasing (T5)", value=True)
                    enable_stage2 = gr.Checkbox(label="Stage 2: Lexical Diversification", value=True)
                    enable_stage3 = gr.Checkbox(label="Stage 3: Discourse Enrichment", value=True)
                    enable_stage4 = gr.Checkbox(label="Stage 4: Structural Variation", value=True)
                    gr.HTML("<div style='padding:8px; border-left:4px solid #3b82f6; border-radius:4px;'> ✅ Final Stage: <b>LLM-powered Text Review</b> applied automatically for quality assurance. </div>")

                with gr.Accordion("Stage 1: Paraphrasing Parameters", open=False):
                    temperature = gr.Slider(0.1, 2.0, value=0.7, step=0.1, label="Temperature")
                    top_p = gr.Slider(0.1, 1.0, value=0.9, step=0.05, label="Top-p")
                    num_beams = gr.Slider(1, 10, value=4, step=1, label="Num Beams")
                    max_length = gr.Slider(128, 1024, value=512, step=64, label="Max Length")
                    repetition_penalty = gr.Slider(1.0, 2.0, value=1.2, step=0.1, label="Repetition Penalty")
                    length_penalty = gr.Slider(0.5, 2.0, value=1.0, step=0.1, label="Length Penalty")
                
                with gr.Accordion("Stage 2: Synonym Replacement Parameters", open=False):
                    synonym_prob = gr.Slider(0.0, 1.0, value=0.3, step=0.05, label="Replacement Probability")
                    min_word_length = gr.Slider(2, 8, value=3, step=1, label="Min Word Length")
                    max_synonyms = gr.Slider(1, 10, value=3, step=1, label="Max Synonyms")
                
                with gr.Accordion("Stage 3: Academic Discourse Parameters", open=False):
                    hedge_prob = gr.Slider(0.0, 0.5, value=0.2, step=0.05, label="Hedge Probability")
                    booster_prob = gr.Slider(0.0, 0.5, value=0.15, step=0.05, label="Booster Probability")
                    connector_prob = gr.Slider(0.0, 0.5, value=0.25, step=0.05, label="Connector Probability")
                    starter_prob = gr.Slider(0.0, 0.3, value=0.1, step=0.05, label="Starter Probability")
                
                with gr.Accordion("Stage 4: Sentence Structure Parameters", open=False):
                    split_prob = gr.Slider(0.0, 1.0, value=0.4, step=0.05, label="Split Probability")
                    merge_prob = gr.Slider(0.0, 1.0, value=0.3, step=0.05, label="Merge Probability")
                    min_split_length = gr.Slider(10, 40, value=20, step=5, label="Min Split Length (words)")
                    max_merge_length = gr.Slider(5, 20, value=10, step=1, label="Max Merge Length (words)")
                    
                with gr.Accordion("Final Stage: LLM Review", open=False):
                    gr.Markdown(
                        """
                        The final stage employs a large language model to review and refine the transformed text. It identifies and corrects any inappropriate word choices, grammatical errors, or inconsistencies to ensure the output is of the highest quality.
                        """
                    )
                    
                with gr.Accordion("About Neural Humanizer", open=False):
                    gr.Markdown(
                        """
                        **Neural Humanizer** is an advanced text transformation tool designed to convert AI-generated content into natural, human-like language. By leveraging a multi-stage pipeline, it enhances text fluency, diversity, and academic integrity.

                        ### Key Features:
                        - **Paraphrasing**: Utilizes state-of-the-art language models to rephrase text while preserving meaning.
                        - **Lexical Diversification**: Replaces words with contextually appropriate synonyms for richer vocabulary.
                        - **Discourse Enrichment**: Adds academic discourse markers to improve formality and coherence.
                        - **Structural Variation**: Modifies sentence structures for enhanced readability.
                        - **LLM-powered Review**: Employs large language models to validate and refine the final output.

                        ### Usage:
                        1. Input your AI-generated text.
                        2. Configure the desired stages and parameters.
                        3. Click "Transform Text" to generate humanized content.

                        ### Note:
                        The final review stage is always applied to ensure the highest quality output.
                        """
                    )
                    
        # Event handlers
        submit_btn.click(
            fn=humanize_text,
            inputs=[
                input_text,
                enable_stage1, enable_stage2, enable_stage3, enable_stage4,
                temperature, top_p, num_beams, max_length, repetition_penalty, length_penalty,
                synonym_prob, min_word_length, max_synonyms,
                hedge_prob, booster_prob, connector_prob, starter_prob,
                split_prob, merge_prob, min_split_length, max_merge_length
            ],
            outputs=[output_text, similarity_output, status_output, ai_content_label_generated, ai_content_score_generated, ai_content_label_input, ai_content_score_input]
        )
        
        clear_btn.click(
            fn=lambda: ("", "", 0.0, "","", 0.0, "", 0.0),
            inputs=[],
            outputs=[input_text, output_text, similarity_output, status_output, ai_content_label_generated, ai_content_score_generated, ai_content_label_input, ai_content_score_input]
        )
        
    return demo

# ============================================================================
# LAUNCH
# ============================================================================
if __name__ == "__main__":
    demo = create_gradio_interface()
    demo.launch(share=True, server_name="0.0.0.0", server_port=7860)