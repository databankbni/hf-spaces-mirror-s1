---
title: NER Explorer Tool
emoji: 🔍
colorFrom: blue
colorTo: gray
sdk: gradio
sdk_version: "4.44.1"
python_version: "3.10"
app_file: app.py
pinned: false
license: mit
---


# 🔍 Named Entity Recognition (NER) Explorer Tool

An interactive web-based tool designed specifically for exploring Named Entity Recognition (NER) in practice. It was developed as a result of the Digital Scholarship at Oxford (DiSc) funded *Extracting Keywords from Crowdsourced Collections* project.

[![Made with Gradio](https://img.shields.io/badge/Made%20with-Gradio-ff7c00?style=flat-square)](https://gradio.app/)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg?style=flat-square)](https://www.python.org/downloads/)

## 📖 What is Named Entity Recognition?

NER is a Natural Language Processing (NLP) technique that automatically identifies and classifies named entities in text into predefined categories such as person, organization, location, date, and more. This tool also supports custom entity types using zero-shot learning with GLiNER.

## 🎯 Background

This NER Explorer Tool is an educational and exploratory interface to enable users to 'play' with different NER models and approaches. It was created in an effort to make the Natural Language Processing (NLP) approach more accessible to Digital Humanities (DH), Galleries, Libraries, Archives and Museums (GLAM) professionals, volunteers and researchers - who might otherwise not have the means or opportunity to explore what they can do with NER.

Simply copy in some text you would like to test the models on or click examples provided if you don't have/wish to use your own text.

## ✨ Why This Tool?

During our short exploratory research project on keyword extraction from crowdsourced collections, we found that NER has real potential for enhancing search and discovery in digital archives while allowing records to 'speak for themselves'.

It can be difficult to know where to start when selecting NER models, as they can work differently and can be used to find different things. So here we've provided access to models that, of those we tested on a small sample, performed the best, while also trying to be clear that no model is perfect.

We also wanted to raise awareness of the existence of zero-shot NER models (e.g. GLiNER) which can be more flexible than models with pre-defined entity types (e.g. spaCy), and show how it's possible to use these together.

## 🚀 How to Use

### Online Version (Easiest)
1. Visit the [Hugging Face Space](https://huggingface.co/spaces/SorrelC/NER-Explorer-Tool)
2. Paste or type your text (or click an example)
3. Select a model from the dropdown
4. Choose standard entity types (PERSON, ORGANIZATION, LOCATION, etc.)
5. Add custom entity types if desired (comma-separated)
6. Adjust the confidence threshold
7. Click "🔍 Analyse Text"
8. Explore results with highlighted text and detailed tables!

## 🛠️ Available Models

The tool includes four NER models selected for their performance on our test samples:

| Model | Type | Description |
|-------|------|-------------|
| **spacy_en_core_web_trf** | Transformer-based | spaCy's transformer model for standard NER |
| **flair_ner-large** | Traditional NER | Flair's large English NER model |
| **flair_ner-ontonotes-large** | OntoNotes-based | Flair model trained on OntoNotes corpus |
| **urchade/gliner_large-v2.11** | Zero-shot | Define your own categories |

## 🎨 Key Features

- **Highlighted Text**: See entities highlighted directly in your text with color-coded labels
- **Split-Color Highlighting**: Entities identified by both common NER models AND custom GLiNER searches are shown with distinctive split-color highlighting (marked with 🤝)
- **Detailed Tables**: Examine all identified entities with confidence scores and source attribution
- **Adjustable Confidence Threshold**: Control how certain models need to be before predicting entities (0.1-0.9)

## 📋 Standard Entity Types

The tool supports 12 standard entity types:

- **PERSON (PER)** - People, including fictional characters
- **ORGANIZATION (ORG)** - Companies, agencies, institutions
- **LOCATION (LOC)** - Non-GPE locations (mountains, bodies of water)
- **GEOPOLITICAL ENTITY (GPE)** - Countries, cities, states
- **DATE** - Absolute or relative dates or periods
- **EVENT** - Named hurricanes, battles, wars, sports events
- **FACILITY (FAC)** - Buildings, airports, highways, bridges
- **PRODUCT** - Objects, vehicles, foods (not services)
- **WORK OF ART** - Titles of books, songs, movies, paintings
- **LANGUAGE (LANG)** - Any named language
- **NATIONALITIES/GROUPS (NORP)** - Nationalities or religious/political groups
- **MISCELLANEOUS (MISC)** - Entities that don't fit elsewhere

## ⚠️ Important Limitations

This tool is designed for exploration and education purposes only.

- ❌ **Not recommended for production use** with very long texts (>2,000 characters)
- ❌ **Not suitable for large collections** or batch processing
- ❌ **Not designed for sensitive materials** without additional review
- ⚠️ **No model is perfect** - all can miss or incorrectly identify entities
- ⚠️ For production use, additional testing, validation, and ethical review are **strongly recommended**

## 💻 Technical Details

Built with:
- [Gradio](https://gradio.app/) for the web interface
- [spaCy](https://spacy.io/) for transformer-based NER
- [Flair](https://github.com/flairNLP/flair) for traditional NER models
- [GLiNER](https://github.com/urchade/GLiNER) for zero-shot entity recognition
- PyTorch for model inference

### Running Locally

```bash
# Clone the repository
git clone https://huggingface.co/spaces/SorrelC/NER-Explorer-Tool
cd NER-Explorer-Tool

# Install dependencies
pip install -r requirements.txt

# Run the app
python app.py
```

Then open your browser to `http://localhost:7860`

## 📚 Learn More

Detailed information about each model:

- **Flair NER Large:** [Hugging Face Model Card](https://huggingface.co/flair/ner-english-large)
- **spaCy Transformer:** [spaCy Documentation](https://spacy.io/models/en#en_core_web_trf)
- **Flair OntoNotes:** [Hugging Face Model Card](https://huggingface.co/flair/ner-english-ontonotes-large)
- **GLiNER:** [Extended Documentation](https://github.com/urchade/GLiNER)

## 🙏 Acknowledgements

This **NER Explorer Tool** was created as part of the [Digital Scholarship at Oxford (DiSc)](https://digitalscholarship.web.ox.ac.uk/) funded research project: *Extracting Keywords from Crowdsourced Collections*.

**See also** [Main EKCC project repository](https://github.com/Digital-Scholarship-Oxford/crowdsourced-data-tools)
**and** [Arana-Catania, M., Conisbee, C., & Kidd, M. (2026). Letting the Data Speak: Extracting Keywords from Crowdsourced Collections with AI (https://doi.org/10.48550/arXiv.2607.09324)](https://doi.org/10.48550/arXiv.2607.09324)  

The code for this tool was developed with the assistance of Claude Opus 4 and later updated using Opus 4.8 (Anthropic).

## 📄 License

MIT

## 📧 Contact

**Questions about this tool?**: [catherine.conisbee@bodleian.ox.ac.uk](mailto:catherine.conisbee@bodleian.ox.ac.uk)


---



Check out the configuration reference at https://huggingface.co/docs/hub/spaces-config-reference
