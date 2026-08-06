import gradio as gr
import random
import nltk
import re
import spacy
from nltk.corpus import wordnet, stopwords
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
from sentence_transformers import SentenceTransformer
import torch
import numpy as np
from typing import List, Dict, Tuple
import logging
from transformers import pipeline


# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
        logger.warning(f"Paraphrasing failed: {e}. Returning original text.")
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
# STAGE 2: SYNONYM REPLACEMENT
# ============================================================================
def get_synonyms(word: str, pos: str, max_synonyms: int = 3) -> List[str]:
    """Get WordNet synonyms"""
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
        for lemma in synset.lemmas()[:5]:
            syn = lemma.name().replace('_', ' ')
            if len(syn.split()) == 1 and syn.lower() != word.lower():
                synonyms.append(syn)
    
    return list(set(synonyms))

def synonym_replace(text: str, prob: float = 0.3, min_word_length: int = 3, 
                   max_synonyms: int = 3) -> str:
    """Replace words with synonyms"""
    from nltk import pos_tag, word_tokenize
    
    stop_words = set(stopwords.words('english'))
    words = word_tokenize(text)
    pos_tags = pos_tag(words)
    new_words = []
    
    for word, pos in pos_tags:
        if not word.isalpha():
            new_words.append(word)
            continue
        
        if word.lower() in stop_words or len(word) <= min_word_length:
            new_words.append(word)
            continue
        
        if random.random() > prob:
            new_words.append(word)
            continue
        
        synonyms = get_synonyms(word, pos, max_synonyms)
        candidates = [s for s in synonyms if s.lower() != word.lower()]
        
        if candidates:
            replacement = random.choice(candidates)
            new_words.append(replacement)
        else:
            new_words.append(word)
    
    return ' '.join(new_words)

# ============================================================================
# STAGE 3: ACADEMIC DISCOURSE
# ============================================================================
def add_academic_discourse(text: str, hedge_prob: float = 0.2, booster_prob: float = 0.15,
                          connector_prob: float = 0.25, starter_prob: float = 0.1) -> str:
    """Add academic discourse elements"""
    
    contractions = {
        "don't": "do not", "doesn't": "does not", "didn't": "did not",
        "can't": "cannot", "couldn't": "could not", "shouldn't": "should not",
        "wouldn't": "would not", "won't": "will not", "aren't": "are not",
        "isn't": "is not", "wasn't": "was not", "weren't": "were not",
        "haven't": "have not", "hasn't": "has not", "hadn't": "had not",
        "I'm": "I am", "I've": "I have", "I'll": "I will", "I'd": "I would",
        "you're": "you are", "you've": "you have", "you'll": "you will",
        "we're": "we are", "we've": "we have", "we'll": "we will",
        "they're": "they are", "they've": "they have", "they'll": "they will",
        "it's": "it is", "that's": "that is", "there's": "there is", "what's": "what is"
    }
    
    hedges = [
        "it appears that", "it is possible that", "the results suggest",
        "it seems that", "there is evidence that", "it may be the case that",
        "to some extent", "in general terms", "one could argue that"
    ]
    
    boosters = [
        "clearly", "indeed", "in fact", "undoubtedly",
        "without doubt", "it is evident that", "there is no question that"
    ]
    
    connectors = {
        "contrast": ["however", "on the other hand", "in contrast", "nevertheless"],
        "addition": ["moreover", "furthermore", "in addition", "what is more"],
        "cause_effect": ["therefore", "thus", "as a result", "consequently", "hence"],
        "example": ["for instance", "for example", "to illustrate"],
        "conclusion": ["in conclusion", "overall", "in summary", "to sum up"]
    }
    
    sentence_starters = [
        "It is important to note that",
        "A key implication is that",
        "The evidence indicates that",
        "The findings suggest that",
        "This demonstrates that",
        "It should be emphasized that",
        "From these observations, it follows that"
    ]
    
    # Expand contractions
    for contraction, expansion in contractions.items():
        pattern = re.compile(r'\b' + re.escape(contraction) + r'\b', re.IGNORECASE)
        text = pattern.sub(expansion, text)
    
    sentences = nltk.sent_tokenize(text)
    modified = []
    
    for i, sent in enumerate(sentences):
        # Add hedge
        if random.random() < hedge_prob and i > 0:
            hedge = random.choice(hedges)
            sent = f"{hedge}, {sent[0].lower() + sent[1:]}"
        
        # Add booster
        elif random.random() < booster_prob:
            booster = random.choice(boosters)
            sent = f"{booster.capitalize()}, {sent}"
        
        # Add starter
        elif random.random() < starter_prob and i > 0:
            starter = random.choice(sentence_starters)
            sent = f"{starter} {sent[0].lower() + sent[1:]}"
        
        # Add connector
        if i > 0 and random.random() < connector_prob:
            conn_type = random.choice(list(connectors.keys()))
            connector = random.choice(connectors[conn_type])
            sent = f"{connector.capitalize()}, {sent[0].lower() + sent[1:]}"
        
        modified.append(sent)
    
    return ' '.join(modified)

# ============================================================================
# STAGE 4: SENTENCE STRUCTURE VARIATION
# ============================================================================
def vary_sentence_structure(text: str, split_prob: float = 0.4, merge_prob: float = 0.3,
                           min_split_length: int = 20, max_merge_length: int = 10) -> str:
    """Vary sentence structure"""
    
    connectors = {
        "contrast": ["however", "nevertheless", "nonetheless", "in contrast"],
        "addition": ["moreover", "furthermore", "in addition", "what is more"],
        "cause_effect": ["therefore", "thus", "consequently", "as a result"],
        "example": ["for example", "for instance", "to illustrate"],
        "conclusion": ["in conclusion", "overall", "in summary"]
    }
    
    all_connectors = {c.lower() for group in connectors.values() for c in group}
    
    def already_has_connector(sentence: str) -> bool:
        lower_sent = sentence.strip().lower()
        return any(lower_sent.startswith(conn) for conn in all_connectors)
    
    def choose_connector_type(prev_sent: str, curr_sent: str) -> str:
        curr_lower = curr_sent.lower()
        
        if any(phrase in curr_lower for phrase in ["such as", "including", "for instance"]):
            return "example"
        elif curr_lower.startswith(("but", "although", "however")):
            return "contrast"
        elif any(phrase in curr_lower for phrase in ["because", "due to", "as a result"]):
            return "cause_effect"
        
        # Semantic similarity fallback
        if prev_sent:
            emb = similarity_model.encode([prev_sent, curr_sent])
            score = np.dot(emb[0], emb[1]) / (np.linalg.norm(emb[0]) * np.linalg.norm(emb[1]))
            return "addition" if score > 0.6 else "contrast"
        
        return "addition"
    
    doc = nlp(text)
    sentences = list(doc.sents)
    modified = []
    
    for idx, sent in enumerate(sentences):
        sent_text = sent.text.strip()
        words = sent_text.split()
        
        # Split long sentences
        if len(words) > min_split_length and random.random() < split_prob:
            split_points = [tok.i - sent.start for tok in sent if tok.dep_ in ("cc", "mark")]
            if split_points:
                split_point = random.choice(split_points)
                tokens = list(sent)
                if 0 < split_point < len(tokens):
                    first = ' '.join([t.text for t in tokens[:split_point]]).strip()
                    second = ' '.join([t.text for t in tokens[split_point+1:]]).strip()
                    if first and second and len(second.split()) > 3:
                        if random.random() < 0.5 and not already_has_connector(second):
                            conn_type = choose_connector_type(first, second)
                            connector = random.choice(connectors[conn_type])
                            second = f"{connector.capitalize()}, {second[0].lower() + second[1:]}"
                        modified.extend([first + '.', second])
                        continue
        
        # Merge short sentences
        if (modified and len(words) < max_merge_length and 
            len(modified[-1].split()) < max_merge_length and random.random() < merge_prob):
            prev_sent = modified[-1]
            if not already_has_connector(sent_text):
                conn_type = choose_connector_type(prev_sent, sent_text)
                connector = random.choice(connectors[conn_type])
                combined = f"{prev_sent.rstrip('.')}; {connector}, {sent_text[0].lower() + sent_text[1:]}"
                modified[-1] = combined
                continue
        
        modified.append(sent_text)
    
    return ' '.join(modified)

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
        logger.error(f"Similarity calculation failed: {e}")
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
            result = synonym_replace(result, synonym_prob, min_word_length, max_synonyms)
            stages_applied.append("Synonym Replacement")
        
        # Stage 3: Academic Discourse
        if enable_stage3:
            result = add_academic_discourse(result, hedge_prob, booster_prob, 
                                           connector_prob, starter_prob)
            stages_applied.append("Academic Discourse")
        
        # Stage 4: Sentence Structure
        if enable_stage4:
            result = vary_sentence_structure(result, split_prob, merge_prob, 
                                            min_split_length, max_merge_length)
            stages_applied.append("Sentence Structure")
        
        # Calculate similarity
        similarity = calculate_similarity(input_text, result)
        ai_content_label_generated, ai_content_score_generated = predict_ai_content(result)
        ai_content_label_input, ai_content_score_input = predict_ai_content(input_text)
        
        # Generate status message
        if not stages_applied:
            status = "⚠️ No stages enabled. Please enable at least one stage."
        else:
            status = f"✅ Successfully applied: {', '.join(stages_applied)}"
        
        return result, similarity, status,ai_content_label_generated, ai_content_score_generated,ai_content_label_input, ai_content_score_input
    
    except Exception as e:
        logger.error(f"Error in humanization: {e}")
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