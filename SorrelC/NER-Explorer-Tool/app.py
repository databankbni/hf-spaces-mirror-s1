import gradio as gr
import torch
from gliner import GLiNER
import pandas as pd
import warnings
import random
import re
import time
warnings.filterwarnings('ignore')

# Common NER entity types (using full names)
STANDARD_ENTITIES = [
    'DATE', 'EVENT', 'FACILITY', 'GEOPOLITICAL ENTITY', 'LANGUAGE', 'LOCATION',
    'MISCELLANEOUS', 'NATIONALITIES/GROUPS', 'ORGANIZATION', 'PERSON', 'PRODUCT', 'WORK OF ART'
]
MODEL_ENTITIES = {
    'flair_ner-large': ['PERSON', 'ORGANIZATION', 'LOCATION', 'MISCELLANEOUS'],
    'spacy_en_core_web_trf': [e for e in STANDARD_ENTITIES if e != 'MISCELLANEOUS'],
    'flair_ner-ontonotes-large': [e for e in STANDARD_ENTITIES if e != 'MISCELLANEOUS'],
    'gliner_urchade/gliner_large-v2.1': STANDARD_ENTITIES,
}

# Colour schemes (updated to match full names)
STANDARD_COLORS = {
    'DATE': '#FF6B6B',                    # Red
    'EVENT': '#4ECDC4',                   # Teal
    'FACILITY': '#45B7D1',                # Blue
    'GEOPOLITICAL ENTITY': '#F9CA24',     # Yellow
    'LANGUAGE': '#6C5CE7',                # Purple
    'LOCATION': '#A0E7E5',                # Light Cyan
    'MISCELLANEOUS': '#FD79A8',           # Pink
    'NATIONALITIES/GROUPS': '#8E8E93',    # Grey
    'ORGANIZATION': '#55A3FF',            # Light Blue
    'PERSON': '#00B894',                  # Green
    'PRODUCT': '#E17055',                 # Orange-Red
    'WORK OF ART': '#DDA0DD'              # Plum
}

# Entity definitions for glossary (alphabetically ordered with full name (abbreviation) format)
ENTITY_DEFINITIONS = {
    'DATE': 'Date (DATE): Absolute or relative dates or periods',
    'EVENT': 'Event (EVENT): Named hurricanes, battles, wars, sports events, etc.',
    'FACILITY': 'Facility (FAC): Buildings, airports, highways, bridges, etc.',
    'GEOPOLITICAL ENTITY': 'Geopolitical Entity (GPE): Countries, cities, states',
    'LANGUAGE': 'Language (LANG): Any named language',
    'LOCATION': 'Location (LOC): Non-GPE locations - Mountain ranges, bodies of water',
    'MISCELLANEOUS': 'Miscellaneous (MISC): Entities that don\'t fit elsewhere',
    'NATIONALITIES/GROUPS': 'Nationalities/Groups (NORP): Nationalities or religious or political groups',
    'ORGANIZATION': 'Organization (ORG): Companies, agencies, institutions, etc.',
    'PERSON': 'Person (PER): People, including fictional characters',
    'PRODUCT': 'Product (PRODUCT): Objects, vehicles, foods, etc. (Not services)',
    'WORK OF ART': 'Work of Art (Work of Art): Titles of books, songs, movies, paintings, etc.'
}

# Additional colours for custom entities
CUSTOM_COLOR_PALETTE = [
    '#FF9F43', '#10AC84', '#EE5A24', '#0FBC89', '#5F27CD',
    '#FF3838', '#2F3640', '#3742FA', '#2ED573', '#FFA502',
    '#FF6348', '#1E90FF', '#FF1493', '#32CD32', '#FFD700',
    '#FF4500', '#DA70D6', '#00CED1', '#FF69B4', '#7B68EE'
]

class HybridNERManager:
    def __init__(self):
        self.gliner_model = None
        self.spacy_model = None
        self.flair_models = {}
        self.all_entity_colors = {}
        self.model_names = [
            'flair_ner-large',
            'spacy_en_core_web_trf', 
            'flair_ner-ontonotes-large',
            'gliner_urchade/gliner_large-v2.1'
        ]
        # Mapping from full names to abbreviations for model compatibility
        self.entity_mapping = {
            'DATE': 'DATE',
            'EVENT': 'EVENT',
            'FACILITY': 'FAC',
            'GEOPOLITICAL ENTITY': 'GPE',
            'LANGUAGE': 'LANG',
            'LOCATION': 'LOC',
            'MISCELLANEOUS': 'MISC',
            'NATIONALITIES/GROUPS': 'NORP',
            'ORGANIZATION': 'ORG',
            'PERSON': 'PER',
            'PRODUCT': 'PRODUCT',
            'WORK OF ART': 'Work of Art'
        }
        # Reverse mapping for display
        self.abbrev_to_full = {v: k for k, v in self.entity_mapping.items()}

    def load_model(self, model_name):
        """Load the specified model"""
        try:
            if 'spacy' in model_name:
                return self.load_spacy_model()
            elif 'flair' in model_name:
                return self.load_flair_model(model_name)
            elif 'gliner' in model_name:
                return self.load_gliner_model()
        except Exception as e:
            print(f"Error loading {model_name}: {str(e)}")
            return None

    def load_spacy_model(self):
        """Load spaCy model for common NER"""
        if self.spacy_model is None:
            try:
                import spacy
                try:
                    # Try transformer model first, fallback to small model
                    self.spacy_model = spacy.load("en_core_web_trf")
                    print("✓ spaCy transformer model loaded successfully")
                except OSError:
                    try:
                        self.spacy_model = spacy.load("en_core_web_sm")
                        print("✓ spaCy common model loaded successfully") 
                    except OSError:
                        print("spaCy model not found. Using GLiNER for all entity types.")
                        return None
            except Exception as e:
                print(f"Error loading spaCy model: {str(e)}")
                return None
        return self.spacy_model

    def load_flair_model(self, model_name):
        """Load Flair models"""
        if model_name not in self.flair_models:
            try:
                from flair.models import SequenceTagger
                if 'ontonotes' in model_name:
                    model = SequenceTagger.load("flair/ner-english-ontonotes-large")
                    print("✓ Flair OntoNotes model loaded successfully")
                else:
                    model = SequenceTagger.load("flair/ner-english-large") 
                    print("✓ Flair large model loaded successfully")
                self.flair_models[model_name] = model
            except Exception as e:
                print(f"Error loading {model_name}: {str(e)}")
                # Fallback to GLiNER
                return self.load_gliner_model()
        return self.flair_models[model_name]

    def load_gliner_model(self):
        """Load GLiNER model for custom entities"""
        if self.gliner_model is None:
            try:
                # Try the tested GLiNER large model first, fallback to medium
                self.gliner_model = GLiNER.from_pretrained("urchade/gliner_large-v2.1")
                print("✓ GLiNER urchade large model loaded successfully")
            except Exception as e:
                print(f"Primary GLiNER model failed: {str(e)}")
                try:
                    # Fallback to stable model
                    self.gliner_model = GLiNER.from_pretrained("urchade/gliner_medium-v2.1")
                    print("✓ GLiNER fallback model loaded successfully")
                except Exception as e2:
                    print(f"Error loading GLiNER model: {str(e2)}")
                    return None
        return self.gliner_model

    def assign_colours(self, standard_entities, custom_entities):
        """Assign colours to all entity types"""
        self.all_entity_colors = {}

        # Assign common colours
        for entity in standard_entities:
            self.all_entity_colors[entity.upper()] = STANDARD_COLORS.get(entity.upper(), '#CCCCCC')

        # Assign custom colours
        for i, entity in enumerate(custom_entities):
            if i < len(CUSTOM_COLOR_PALETTE):
                self.all_entity_colors[entity.upper()] = CUSTOM_COLOR_PALETTE[i]
            else:
                # Generate random colour if we run out
                self.all_entity_colors[entity.upper()] = f"#{random.randint(0, 0xFFFFFF):06x}"

        return self.all_entity_colors

    def extract_entities_by_model(self, text, entity_types, model_name, threshold=0.3):
        """Extract entities using the specified model"""
        # Convert full names to abbreviations for model processing
        abbrev_types = []
        for entity in entity_types:
            if entity in self.entity_mapping:
                abbrev_types.append(self.entity_mapping[entity])
            else:
                abbrev_types.append(entity)
        
        if 'spacy' in model_name:
            return self.extract_spacy_entities(text, abbrev_types)
        elif 'flair' in model_name:
            return self.extract_flair_entities(text, abbrev_types, model_name)
        elif 'gliner' in model_name:
            # GLiNER reads labels as words, so give it the full names (lowercased)
            # rather than abbreviations like NORP/FAC/MISC.
            gliner_types = [e.lower() for e in entity_types]
            return self.extract_gliner_entities(text, gliner_types, threshold, is_custom=False)
        else:
            return []

    def extract_spacy_entities(self, text, entity_types):
        """Extract entities using spaCy"""
        model = self.load_spacy_model()
        if model is None:
            return []

        try:
            doc = model(text)
            entities = []
            for ent in doc.ents:
                if ent.label_ in entity_types:
                    # Convert abbreviation back to full name for display
                    display_label = self.abbrev_to_full.get(ent.label_, ent.label_)
                    entities.append({
                        'text': ent.text,
                        'label': display_label,
                        'start': ent.start_char,
                        'end': ent.end_char,
                        'confidence': 1.0,  # spaCy doesn't provide confidence scores
                        'source': 'spaCy'
                    })
            return entities
        except Exception as e:
            print(f"Error with spaCy extraction: {str(e)}")
            return []

    def extract_flair_entities(self, text, entity_types, model_name):
        """Extract entities using Flair"""
        model = self.load_flair_model(model_name)
        if model is None:
            return []

        try:
            from flair.data import Sentence
            sentence = Sentence(text)
            model.predict(sentence)
            entities = []
            for entity in sentence.get_spans('ner'):
                # Map Flair labels to our common set
                label = entity.tag
                if label == 'PERSON':
                    label = 'PER'
                elif label == 'ORGANIZATION':
                    label = 'ORG'
                elif label == 'LOCATION':
                    label = 'LOC'
                elif label == 'MISCELLANEOUS':
                    label = 'MISC'

                if label in entity_types:
                    # Convert abbreviation back to full name for display
                    display_label = self.abbrev_to_full.get(label, label)
                    entities.append({
                        'text': entity.text,
                        'label': display_label,
                        'start': entity.start_position,
                        'end': entity.end_position,
                        'confidence': entity.score,
                        'source': f'Flair-{model_name.split("-")[-1]}'
                    })
            return entities
        except Exception as e:
            print(f"Error with Flair extraction: {str(e)}")
            return []

    def extract_gliner_entities(self, text, entity_types, threshold=0.3, is_custom=True):
        """Extract entities using GLiNER"""
        model = self.load_gliner_model()
        if model is None:
            return []

        try:
            entities = model.predict_entities(text, entity_types, threshold=threshold)
            result = []
            for entity in entities:
                # Convert abbreviation back to full name for display if not custom
                if not is_custom:
                    display_label = self.abbrev_to_full.get(entity['label'].upper(), entity['label'].upper())
                else:
                    display_label = entity['label'].upper()
                    
                result.append({
                    'text': entity['text'],
                    'label': display_label,
                    'start': entity['start'],
                    'end': entity['end'],
                    'confidence': entity.get('score', 0.0),
                    'source': 'GLiNER-Custom' if is_custom else 'GLiNER-Common'
                })
            return result
        except Exception as e:
            print(f"Error with GLiNER extraction: {str(e)}")
            return []

def find_overlapping_entities(entities):
    """Find and share overlapping entities - specifically entities found by BOTH common NER models AND custom entities"""
    if not entities:
        return []

    # Sort entities by start position
    sorted_entities = sorted(entities, key=lambda x: x['start'])
    shared_entities = []

    i = 0
    while i < len(sorted_entities):
        current_entity = sorted_entities[i]
        overlapping_entities = [current_entity]

        # Find all entities that overlap with current entity
        j = i + 1
        while j < len(sorted_entities):
            next_entity = sorted_entities[j]

            # Check if entities overlap (same text span or overlapping positions)
            if (current_entity['start'] <= next_entity['start'] < current_entity['end'] or
                next_entity['start'] <= current_entity['start'] < current_entity['end'] or
                current_entity['text'].lower() == next_entity['text'].lower()):
                overlapping_entities.append(next_entity)
                sorted_entities.pop(j)
            else:
                j += 1

        # Create shared entity only if we have BOTH common and custom entities
        if len(overlapping_entities) == 1:
            shared_entities.append(overlapping_entities[0])
        else:
            # Check if this is a true "shared" entity (common + custom)
            has_common = False
            has_custom = False
            
            for entity in overlapping_entities:
                source = entity.get('source', '')
                if source in ['spaCy', 'GLiNER-Common'] or source.startswith('Flair-'):
                    has_common = True
                elif source == 'GLiNER-Custom':
                    has_custom = True
            
            if has_common and has_custom:
                # This is a true shared entity (common + custom)
                shared_entity = share_entities(overlapping_entities)
                shared_entities.append(shared_entity)
            else:
                # These are just overlapping entities from the same source type, keep separate
                shared_entities.extend(overlapping_entities)

        i += 1

    return shared_entities

def share_entities(entity_list):
    """Share multiple overlapping entities into one"""
    if len(entity_list) == 1:
        return entity_list[0]

    # Use the entity with the longest text span as the base
    base_entity = max(entity_list, key=lambda x: len(x['text']))

    # Collect all labels and sources
    labels = [entity['label'] for entity in entity_list]
    sources = [entity['source'] for entity in entity_list]
    confidences = [entity['confidence'] for entity in entity_list]

    return {
        'text': base_entity['text'],
        'start': base_entity['start'],
        'end': base_entity['end'],
        'labels': labels,
        'sources': sources,
        'confidences': confidences,
        'is_shared': True,
        'entity_count': len(entity_list)
    }

def create_highlighted_html(text, entities, entity_colors):
    """Create HTML with highlighted entities"""
    if not entities:
        return f"<div style='padding: 15px; border: 1px solid #ddd; border-radius: 5px; background-color: #fafafa;'><p>{text}</p></div>"

    # Find and share overlapping entities
    shared_entities = find_overlapping_entities(entities)

    # Sort by start position
    sorted_entities = sorted(shared_entities, key=lambda x: x['start'])

    # Create HTML with highlighting
    html_parts = []
    last_end = 0

    for entity in sorted_entities:
        # Add text before entity
        html_parts.append(text[last_end:entity['start']])

        if entity.get('is_shared', False):
            # Handle shared entity with multiple colours
            html_parts.append(create_shared_entity_html(entity, entity_colors))
        else:
            # Handle single entity
            html_parts.append(create_single_entity_html(entity, entity_colors))

        last_end = entity['end']

    # Add remaining text
    html_parts.append(text[last_end:])

    highlighted_text = ''.join(html_parts)

    return f"""
    <div style='padding: 15px; border: 2px solid #ddd; border-radius: 8px; background-color: #fafafa; margin: 10px 0;'>
        <h4 style='margin: 0 0 15px 0; color: #333;'>📝 Text with Highlighted Entities</h4>
        <div style='line-height: 1.8; font-size: 16px; background-color: white; padding: 15px; border-radius: 5px;'>{highlighted_text}</div>
    </div>
    """

def create_single_entity_html(entity, entity_colors):
    """Create HTML for a single entity"""
    label = entity['label']
    colour = entity_colors.get(label.upper(), '#CCCCCC')
    confidence = entity.get('confidence', 0.0)
    source = entity.get('source', 'Unknown')

    return (f'<span style="background-color: {colour}; padding: 2px 4px; '
            f'border-radius: 3px; margin: 0 1px; '
            f'border: 1px solid {colour}; color: white; font-weight: bold;" '
            f'title="{label} ({source}) - confidence: {confidence:.2f}">'
            f'{entity["text"]}</span>')

def create_shared_entity_html(entity, entity_colors):
    """Create HTML for a shared entity with multiple colours"""
    labels = entity['labels']
    sources = entity['sources']
    confidences = entity['confidences']

    # Get colours for each label
    colours = []
    for label in labels:
        colour = entity_colors.get(label.upper(), '#CCCCCC')
        colours.append(colour)

    # Create gradient background
    if len(colours) == 2:
        gradient = f"linear-gradient(to right, {colours[0]} 50%, {colours[1]} 50%)"
    else:
        # For more colours, create equal segments
        segment_size = 100 / len(colours)
        gradient_parts = []
        for i, colour in enumerate(colours):
            start = i * segment_size
            end = (i + 1) * segment_size
            gradient_parts.append(f"{colour} {start}%, {colour} {end}%")
        gradient = f"linear-gradient(to right, {', '.join(gradient_parts)})"

    # Create tooltip
    tooltip_parts = []
    for i, label in enumerate(labels):
        tooltip_parts.append(f"{label} ({sources[i]}) - {confidences[i]:.2f}")
    tooltip = " | ".join(tooltip_parts)

    return (f'<span style="background: {gradient}; padding: 2px 4px; '
            f'border-radius: 3px; margin: 0 1px; '
            f'border: 2px solid #333; color: white; font-weight: bold;" '
            f'title="SHARED: {tooltip}">'
            f'{entity["text"]} 🤝</span>')

def create_entity_table_html(entities_of_type, entity_type, colour, is_shared=False):
    """Create HTML table for a specific entity type"""
    if is_shared:
        table_html = f"""
        <table style="width: 100%; border-collapse: collapse; border: 1px solid #ddd;">
            <thead>
                <tr style="background-color: {colour}; color: white;">
                    <th style="padding: 12px; text-align: left; border: 1px solid #ddd;">Entity Text</th>
                    <th style="padding: 12px; text-align: left; border: 1px solid #ddd;">All Labels</th>
                    <th style="padding: 12px; text-align: left; border: 1px solid #ddd;">Sources</th>
                    <th style="padding: 12px; text-align: left; border: 1px solid #ddd;">Count</th>
                </tr>
            </thead>
            <tbody>
        """
        
        for entity in entities_of_type:
            labels_text = " | ".join(entity['labels'])
            sources_text = " | ".join(entity['sources'])
            
            table_html += f"""
                    <tr style="background-color: #fff;">
                        <td style="padding: 10px; border: 1px solid #ddd; font-weight: bold;">{entity['text']}</td>
                        <td style="padding: 10px; border: 1px solid #ddd;">{labels_text}</td>
                        <td style="padding: 10px; border: 1px solid #ddd;">{sources_text}</td>
                        <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">
                            <span style='background-color: #28a745; color: white; padding: 2px 6px; border-radius: 10px; font-size: 11px;'>
                                {entity['entity_count']}
                            </span>
                        </td>
                    </tr>
            """
    else:
        table_html = f"""
        <table style="width: 100%; border-collapse: collapse; border: 1px solid #ddd;">
            <thead>
                <tr style="background-color: {colour}; color: white;">
                    <th style="padding: 12px; text-align: left; border: 1px solid #ddd;">Entity Text</th>
                    <th style="padding: 12px; text-align: left; border: 1px solid #ddd;">Confidence</th>
                    <th style="padding: 12px; text-align: left; border: 1px solid #ddd;">Type</th>
                    <th style="padding: 12px; text-align: left; border: 1px solid #ddd;">Source</th>
                </tr>
            </thead>
            <tbody>
        """
        
        # Sort by confidence score
        entities_of_type.sort(key=lambda x: x.get('confidence', 0), reverse=True)
        
        for entity in entities_of_type:
            confidence = entity.get('confidence', 0.0)
            confidence_colour = "#28a745" if confidence > 0.7 else "#ffc107" if confidence > 0.4 else "#dc3545"
            source = entity.get('source', 'Unknown')
            source_badge = f"<span style='background-color: #007bff; color: white; padding: 2px 6px; border-radius: 10px; font-size: 11px;'>{source}</span>"
            
            table_html += f"""
                    <tr style="background-color: #fff;">
                        <td style="padding: 10px; border: 1px solid #ddd; font-weight: bold;">{entity['text']}</td>
                        <td style="padding: 10px; border: 1px solid #ddd;">
                            <span style="color: {confidence_colour}; font-weight: bold;">
                                {confidence:.3f}
                            </span>
                        </td>
                        <td style="padding: 10px; border: 1px solid #ddd;">{entity['label']}</td>
                        <td style="padding: 10px; border: 1px solid #ddd;">{source_badge}</td>
                    </tr>
            """
    
    table_html += "</tbody></table>"
    return table_html

def create_all_entity_tables(entities, entity_colors):
    """Create all entity tables in a single container"""
    if not entities:
        return "<p style='text-align: center; padding: 20px;'>No entities found.</p>"

    # Share overlapping entities
    shared_entities = find_overlapping_entities(entities)

    # Group entities by type
    entity_groups = {}
    for entity in shared_entities:
        if entity.get('is_shared', False):
            key = 'SHARED_ENTITIES'
        else:
            key = entity['label']
        
        if key not in entity_groups:
            entity_groups[key] = []
        entity_groups[key].append(entity)

    if not entity_groups:
        return "<p style='text-align: center; padding: 20px;'>No entities found.</p>"

    # Create container with all tables
    all_tables_html = """
    <div style='max-height: 600px; overflow-y: auto; border: 2px solid #ddd; border-radius: 8px; padding: 20px; background-color: #fafafa;'>
        <style>
            .entity-section {
                margin-bottom: 30px;
                background-color: white;
                border-radius: 8px;
                padding: 15px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            .entity-section:last-child {
                margin-bottom: 0;
            }
            .section-header {
                display: flex;
                align-items: center;
                margin-bottom: 15px;
                padding-bottom: 10px;
                border-bottom: 2px solid #eee;
            }
            .entity-count {
                background-color: #007bff;
                color: white;
                padding: 4px 12px;
                border-radius: 15px;
                font-size: 14px;
                font-weight: bold;
                margin-left: 10px;
            }
            .quick-nav {
                position: sticky;
                top: 0;
                background-color: #f8f9fa;
                padding: 10px;
                margin-bottom: 20px;
                border-radius: 8px;
                display: flex;
                flex-wrap: wrap;
                gap: 8px;
                z-index: 10;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            .nav-button {
                padding: 6px 12px;
                border: 1px solid #ddd;
                border-radius: 20px;
                background-color: white;
                cursor: pointer;
                transition: all 0.3s;
                text-decoration: none;
                color: #333;
                font-size: 13px;
                font-weight: 500;
            }
            .nav-button:hover {
                background-color: #4ECDC4;
                color: white;
                border-color: #4ECDC4;
            }
        </style>
    """
    
    # Create quick navigation
    all_tables_html += '<div class="quick-nav">'
    all_tables_html += '<strong style="margin-right: 10px;">Quick Navigation:</strong>'
    
    # Sort entity groups to show shared entities first
    sorted_groups = []
    if 'SHARED_ENTITIES' in entity_groups:
        sorted_groups.append(('SHARED_ENTITIES', entity_groups['SHARED_ENTITIES']))
    
    for entity_type, entities_list in sorted(entity_groups.items()):
        if entity_type != 'SHARED_ENTITIES':
            sorted_groups.append((entity_type, entities_list))
    
    for entity_type, entities_list in sorted_groups:
        if entity_type == 'SHARED_ENTITIES':
            icon = '🤝'
            label = 'Shared'
        else:
            icon = '🎯' if entity_type in STANDARD_ENTITIES else '✨'
            label = entity_type
        
        all_tables_html += f'<a href="#{entity_type.replace(" ", "_")}" class="nav-button">{icon} {label} ({len(entities_list)})</a>'
    
    all_tables_html += '</div>'
    
    # Add shared entities section if any
    if 'SHARED_ENTITIES' in entity_groups:
        shared_entities_list = entity_groups['SHARED_ENTITIES']
        all_tables_html += f"""
        <div class="entity-section" id="SHARED_ENTITIES">
            <div class="section-header">
                <h3 style="margin: 0; display: flex; align-items: center;">
                    <span style="font-size: 24px; margin-right: 10px;">🤝</span>
                    Shared Entities
                    <span class="entity-count">{len(shared_entities_list)} found</span>
                </h3>
            </div>
            {create_entity_table_html(shared_entities_list, 'SHARED_ENTITIES', '#666666', is_shared=True)}
        </div>
        """
    
    # Add other entity types
    for entity_type, entities_of_type in sorted(entity_groups.items()):
        if entity_type == 'SHARED_ENTITIES':
            continue
            
        colour = entity_colors.get(entity_type.upper(), '#f0f0f0')
        is_standard = entity_type in STANDARD_ENTITIES
        icon = "🎯" if is_standard else "✨"
        type_label = "Common NER" if is_standard else "Custom GLiNER"
        
        all_tables_html += f"""
        <div class="entity-section" id="{entity_type.replace(' ', '_')}">
            <div class="section-header">
                <h3 style="margin: 0; display: flex; align-items: center;">
                    <span style="font-size: 24px; margin-right: 10px;">{icon}</span>
                    {entity_type}
                    <span class="entity-count" style="background-color: {colour};">{len(entities_of_type)} found</span>
                </h3>
                <span style="margin-left: auto; color: #666; font-size: 14px;">{type_label}</span>
            </div>
            {create_entity_table_html(entities_of_type, entity_type, colour)}
        </div>
        """
    
    all_tables_html += "</div>"
    
    return all_tables_html

def create_legend_html(entity_colors, standard_entities, custom_entities):
    """Create a legend showing entity colours"""
    if not entity_colors:
        return ""

    html = "<div style='margin: 15px 0; padding: 15px; background-color: #f8f9fa; border-radius: 8px;'>"
    html += "<h4 style='margin: 0 0 15px 0;'>🎨 Entity Type Legend</h4>"

    if standard_entities:
        html += "<div style='margin-bottom: 15px;'>"
        html += "<h5 style='margin: 0 0 8px 0;'>🎯 Common Entities:</h5>"
        html += "<div style='display: flex; flex-wrap: wrap; gap: 8px;'>"
        for entity_type in standard_entities:
            colour = entity_colors.get(entity_type.upper(), '#ccc')
            html += f"<span style='background-color: {colour}; padding: 4px 8px; border-radius: 15px; color: white; font-weight: bold; font-size: 12px;'>{entity_type}</span>"
        html += "</div></div>"

    if custom_entities:
        html += "<div>"
        html += "<h5 style='margin: 0 0 8px 0;'>✨ Custom Entities:</h5>"
        html += "<div style='display: flex; flex-wrap: wrap; gap: 8px;'>"
        for entity_type in custom_entities:
            colour = entity_colors.get(entity_type.upper(), '#ccc')
            html += f"<span style='background-color: {colour}; padding: 4px 8px; border-radius: 15px; color: white; font-weight: bold; font-size: 12px;'>{entity_type}</span>"
        html += "</div></div>"

    html += "</div>"
    return html

# Initialize the NER manager
ner_manager = HybridNERManager()

def process_text(text, standard_entities, custom_entities_str, confidence_threshold, selected_model, progress=gr.Progress()):
    """Main processing function for Gradio interface with progress tracking"""
    if not text.strip():
        return "❌ Please enter some text to analyse", "", "", gr.update(visible=False)

    progress(0.1, desc="Initialising...")
    
    # Parse custom entities
    custom_entities = []
    if custom_entities_str.strip():
        custom_entities = [entity.strip() for entity in custom_entities_str.split(',') if entity.strip()]

    # Parse common entities
    selected_standard = [entity for entity in standard_entities if entity]

    if not selected_standard and not custom_entities:
        return "❌ Please select at least one common entity type OR enter custom entity types", "", "", gr.update(visible=False)

    progress(0.2, desc="Loading models...")
    
    all_entities = []

    # Extract common entities using selected model
    if selected_standard and selected_model:
        progress(0.4, desc="Extracting common entities...")
        standard_entities_results = ner_manager.extract_entities_by_model(text, selected_standard, selected_model, confidence_threshold)
        all_entities.extend(standard_entities_results)

    # Extract custom entities using GLiNER
    if custom_entities:
        progress(0.6, desc="Extracting custom entities...")
        custom_entity_results = ner_manager.extract_gliner_entities(text, custom_entities, confidence_threshold, is_custom=True)
        all_entities.extend(custom_entity_results)

    if not all_entities:
        return "❌ No entities found. Try lowering the confidence threshold or using different entity types.", "", "", gr.update(visible=False)

    progress(0.8, desc="Processing results...")
    
    # Assign colours
    entity_colors = ner_manager.assign_colours(selected_standard, custom_entities)

    # Create outputs
    legend_html = create_legend_html(entity_colors, selected_standard, custom_entities)
    highlighted_html = create_highlighted_html(text, all_entities, entity_colors)
    results_html = create_all_entity_tables(all_entities, entity_colors)

    progress(0.9, desc="Creating summary...")
    
    # Create summary with shared entities terminology
    total_entities = len(all_entities)
    shared_entities = find_overlapping_entities(all_entities)
    final_count = len(shared_entities)
    shared_count = sum(1 for e in shared_entities if e.get('is_shared', False))

    summary = f"""
    ## 📊 Analysis Summary
    - **Total entities found:** {total_entities}
    - **Final entities displayed:** {final_count}
    - **Shared entities:** {shared_count}
    - **Average confidence:** {sum(e.get('confidence', 0) for e in all_entities) / total_entities:.3f}
    """

    progress(1.0, desc="Complete!")
    
    return summary, legend_html + highlighted_html, results_html, gr.update(visible=True)

# Create Gradio interface
def create_interface():
    with gr.Blocks(title="Hybrid NER + GLiNER Tool", theme=gr.themes.Soft()) as demo:
        gr.Markdown("""
        # Named Entity Recognition (NER) Explorer Tool
        
        Combine common Named Entity Recognition (NER) categories with your own custom entity types! 
        This tool uses both traditional NER models and GLiNER for comprehensive entity extraction, allowing you to explore what NER looks like in practice.
          
        ### How to use this tool:
        1. **📝 Enter your text** in the text area below
        2. **🎯 Select a model** from the dropdown menu
        3. **☑️ Select common entity types** you want to identify (PERSON, ORGANIZATION, LOCATION, etc.)
        4. **✨ Add custom entities** (comma-separated) like "relationships, occupations, skills"
        5. **⚙️ Adjust confidence threshold** 
        6. **🔍 Click "Analyse Text"** to see results
                (NB: common/custom entities which overlap are shown with split-colour highlighting)
        7. **🔄 Refresh the page** to try again with new text
        """)
        # Add tip box
        gr.HTML("""
        <div style="background-color: #fff3cd; border: 1px solid #ffeaa7; border-radius: 8px; padding: 12px; margin: 15px 0;">
            <strong style="color: #856404;">💡 Top tip:</strong> No model is perfect - all can miss and/or incorrectly identify entity types.
        </div>
        """)
        
        with gr.Row():
            with gr.Column(scale=2):
                text_input = gr.Textbox(
                    label="📝 Text to Analyse",
                    placeholder="Enter your text here...",
                    lines=12,
                    max_lines=20
                )
            
            with gr.Column(scale=1):
                confidence_threshold = gr.Slider(
                    minimum=0.1,
                    maximum=0.9,
                    value=0.3,
                    step=0.1,
                    label="🎚️ GLiNER Confidence Threshold"
                )
                
                # Add confidence threshold explanation
                gr.HTML("""
                <details style="margin: 10px 0; padding: 10px; background-color: #f8f9fa; border-radius: 8px; border: 1px solid #ddd;">
                    <summary style="cursor: pointer; font-weight: bold; padding: 5px; color: #1976d2;">
                        ℹ️ Understanding the Confidence Threshold
                    </summary>
                    <div style="margin-top: 10px; padding: 10px; font-size: 14px;">
                        <p style="margin: 0 0 10px 0;">The <strong>confidence threshold</strong> controls how certain the model needs to be before identifying an entity:</p>
                        <ul style="margin: 0; padding-left: 20px;">
                            <li><strong>Lower values (0.1-0.3):</strong> More entities detected, but may include false positives</li>
                            <li><strong>Medium values (0.4-0.6):</strong> Balanced detection with moderate confidence</li>
                            <li><strong>Higher values (0.7-0.9):</strong> Only highly confident entities detected, may miss some valid entities</li>
                        </ul>
                        <p style="margin: 10px 0 0 0; font-style: italic;"><strong>Top Tip:</strong> Start with 0.3 for comprehensive detection, then adjust based on your needs.</p>
                    </div>
                </details>
                """)
        
        with gr.Row():
            with gr.Column():
                gr.Markdown("### 🎯 Common Entity Types")
                
                # Model selector
                model_dropdown = gr.Dropdown(
                    choices=ner_manager.model_names,
                    value=ner_manager.model_names[0],
                    label="Select NER Model for Common Entities"
                )
                
                # Common entities with select all functionality
                standard_entities = gr.CheckboxGroup(
                    choices=MODEL_ENTITIES[ner_manager.model_names[0]],
                    value=['PERSON', 'ORGANIZATION', 'LOCATION', 'MISCELLANEOUS'],  # Default selection with full names
                    label="Select Common Entities"
                )
                
                # Select/Deselect All button
                with gr.Row():
                    select_all_btn = gr.Button("🔘 Deselect All", size="sm")
                    
                # Function for select/deselect all
                def toggle_all_entities(current_selection, selected_model):
                    allowed = MODEL_ENTITIES.get(selected_model, STANDARD_ENTITIES)
                    if len(current_selection) > 0:
                        # If any are selected, deselect all
                        return [], "☑️ Select All"
                    else:
                        # If none selected, select all
                        return allowed, "🔘 Deselect All"
                
                select_all_btn.click(
                    fn=toggle_all_entities,
                    inputs=[standard_entities, model_dropdown],
                    outputs=[standard_entities, select_all_btn]
                )
                def update_entity_choices(selected_model, current_selection):
                    allowed = MODEL_ENTITIES.get(selected_model, STANDARD_ENTITIES)
                    kept = [e for e in current_selection if e in allowed]
                    if not kept:
                        kept = [e for e in ['PERSON', 'ORGANIZATION', 'LOCATION'] if e in allowed]
                    return gr.update(choices=allowed, value=kept)

                model_dropdown.change(
                    fn=update_entity_choices,
                    inputs=[model_dropdown, standard_entities],
                    outputs=[standard_entities]
                )
            
            with gr.Column():
                gr.Markdown("### ✨ Custom Entity Types - Powered by GLiNER")
                custom_entities = gr.Textbox(
                    label="Custom Entities (comma-separated)",
                    placeholder="e.g. relationships, civilian occupations, emotions",
                    lines=3
                )
                gr.Markdown("""
                **Examples:**
                - relationships, occupations, skills
                - emotions, actions, objects  
                - medical conditions, treatments
                
                
                
                """)
        
        # Add glossary (alphabetically ordered)
        gr.HTML("""
        <details style="margin: 20px 0; padding: 10px; background-color: #f8f9fa; border-radius: 8px; border: 1px solid #ddd;">
            <summary style="cursor: pointer; font-weight: bold; padding: 5px; color: #1976d2;">
                ℹ️ Entity Type Definitions
            </summary>
            <div style="margin-top: 10px; padding: 10px;">
                <dl style="margin: 0; font-size: 14px;">
                    <div style="margin-bottom: 8px;">
                        <dt style="font-weight: bold; display: inline; color: #FF6B6B;">Date (DATE):</dt>
                        <dd style="display: inline; margin-left: 5px;">Absolute or relative dates or periods</dd>
                    </div>
                    <div style="margin-bottom: 8px;">
                        <dt style="font-weight: bold; display: inline; color: #4ECDC4;">Event (EVENT):</dt>
                        <dd style="display: inline; margin-left: 5px;">Named hurricanes, battles, wars, sports events, etc.</dd>
                    </div>
                    <div style="margin-bottom: 8px;">
                        <dt style="font-weight: bold; display: inline; color: #45B7D1;">Facility (FAC):</dt>
                        <dd style="display: inline; margin-left: 5px;">Buildings, airports, highways, bridges, etc.</dd>
                    </div>
                    <div style="margin-bottom: 8px;">
                        <dt style="font-weight: bold; display: inline; color: #F9CA24;">Geopolitical Entity (GPE):</dt>
                        <dd style="display: inline; margin-left: 5px;">Countries, cities, states</dd>
                    </div>
                    <div style="margin-bottom: 8px;">
                        <dt style="font-weight: bold; display: inline; color: #6C5CE7;">Language (LANG):</dt>
                        <dd style="display: inline; margin-left: 5px;">Any named language</dd>
                    </div>
                    <div style="margin-bottom: 8px;">
                        <dt style="font-weight: bold; display: inline; color: #A0E7E5;">Location (LOC):</dt>
                        <dd style="display: inline; margin-left: 5px;">Non-GPE locations - Mountain ranges, bodies of water</dd>
                    </div>
                    <div style="margin-bottom: 8px;">
                        <dt style="font-weight: bold; display: inline; color: #FD79A8;">Miscellaneous (MISC):</dt>
                        <dd style="display: inline; margin-left: 5px;">Entities that don't fit elsewhere</dd>
                    </div>
                    <div style="margin-bottom: 8px;">
                        <dt style="font-weight: bold; display: inline; color: #8E8E93;">Nationalities/Groups (NORP):</dt>
                        <dd style="display: inline; margin-left: 5px;">Nationalities or religious or political groups</dd>
                    </div>
                    <div style="margin-bottom: 8px;">
                        <dt style="font-weight: bold; display: inline; color: #55A3FF;">Organization (ORG):</dt>
                        <dd style="display: inline; margin-left: 5px;">Companies, agencies, institutions, etc.</dd>
                    </div>
                    <div style="margin-bottom: 8px;">
                        <dt style="font-weight: bold; display: inline; color: #00B894;">Person (PER):</dt>
                        <dd style="display: inline; margin-left: 5px;">People, including fictional characters</dd>
                    </div>
                    <div style="margin-bottom: 8px;">
                        <dt style="font-weight: bold; display: inline; color: #E17055;">Product (PRODUCT):</dt>
                        <dd style="display: inline; margin-left: 5px;">Objects, vehicles, foods, etc. (Not services)</dd>
                    </div>
                    <div style="margin-bottom: 8px;">
                        <dt style="font-weight: bold; display: inline; color: #DDA0DD;">Work of Art (Work of Art):</dt>
                        <dd style="display: inline; margin-left: 5px;">Titles of books, songs, movies, paintings, etc.</dd>
                    </div>
                </dl>
            </div>
        </details>
        """)
        
        analyse_btn = gr.Button("🔍 Analyse Text", variant="primary", size="lg")
        
        # Add horizontal line separator after the button
        gr.HTML("<hr style='margin-top: 20px; margin-bottom: 15px;'>")
        
        # Output sections
        with gr.Row():
            summary_output = gr.Markdown(label="Summary")
        
        with gr.Row():
            highlighted_output = gr.HTML(label="Highlighted Text")
        
        # Results section (initially hidden)
        with gr.Row(visible=False) as results_row:
            with gr.Column():
                gr.Markdown("### 📋 Detailed Results")
                results_output = gr.HTML(label="Entity Results")
        
        # Connect the button to the processing function
        analyse_btn.click(
            fn=process_text,
            inputs=[
                text_input,
                standard_entities,
                custom_entities,
                confidence_threshold,
                model_dropdown
            ],
            outputs=[summary_output, highlighted_output, results_output, results_row]
        )
        
        # Updated examples text with reduced spacing
        with gr.Column():
            gr.Markdown("""
            ### 💡 No example text to test? No problem!
            Simply click on one of the examples provided below, and the fields will be populated for you.
            """, elem_id="examples-heading")
        
        gr.Examples(
            examples=[
                [
                    "On June 6, 1944, Allied forces launched Operation Overlord, the invasion of Normandy. General Dwight D. Eisenhower commanded the operation, while Field Marshal Bernard Montgomery led ground forces. The BBC broadcast coded messages to the French Resistance, including the famous line 'The long sobs of autumn violins.'",
                    ["PERSON", "ORGANIZATION", "LOCATION", "DATE", "EVENT"],
                    "military operations, military ranks, historical battles",
                    0.3,
                    "spacy_en_core_web_trf"
                ],
                [
                    "In Jane Austen's 'Pride and Prejudice', Elizabeth Bennet first meets Mr. Darcy at the Meryton assembly. The novel, published in 1813, explores themes of marriage and social class in Regency England. Austen wrote to her sister Cassandra about the manuscript while staying at Chawton Cottage.",
                    ["PERSON", "LOCATION", "DATE", "WORK OF ART"],
                    "literary themes, relationships, literary periods",
                    0.3,
                    "gliner_urchade/gliner_large-v2.1"
                ],
                [
                    "Charles Darwin arrived at the Galápagos Islands aboard HMS Beagle in September 1835. During his five-week visit, Darwin collected specimens of finches, tortoises, and mockingbirds. His observations of these species' variations across different islands later contributed to his theory of evolution by natural selection, published in 'On the Origin of Species' in 1859.",
                    ["PERSON", "LOCATION"],
                    "date, book title, ship, scientific concepts, species",
                    0.3,
                    "flair_ner-large"
                ]
            ],
            inputs=[
                text_input,
                standard_entities,
                custom_entities,
                confidence_threshold,
                model_dropdown
            ],
            label="Examples"
        )
        
        # Add custom CSS to make Examples label black and improve entity label readability
        gr.HTML("""
        <style>
            /* Make the Examples label text black */
            .gradio-examples-label {
                color: black !important;
            }
            /* Also target the label more specifically if needed */
            h4.examples-label, .examples-label {
                color: black !important;
            }
            /* Override any link colors in the examples section */
            #examples-heading + div label,
            #examples-heading + div .label-text {
                color: black !important;
            }
            
            /* Improve readability of entity checkbox labels */
            .gradio-checkbox-group label {
                font-size: 14px !important;
                font-weight: normal !important;
                color: #333333 !important;
                line-height: 1.5 !important;
            }
            
            /* Make the checkbox labels match the entity definitions style */
            input[type="checkbox"] + span {
                font-size: 14px !important;
                color: #333333 !important;
            }
        </style>
        """)
        
        # Add model information links
        gr.HTML("""
        <hr style="margin-top: 40px; margin-bottom: 20px;">
        <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin-top: 20px;">
            <h4 style="margin-top: 0;">📚 Model Information & Documentation (incl. details on usage terms)</h4>
            <p style="font-size: 14px; margin-bottom: 15px;">Learn more about the models used in this tool:</p>
            <ul style="font-size: 14px; line-height: 1.8;">
                <li><strong>flair_ner-large:</strong> 
                    <a href="https://huggingface.co/flair/ner-english-large" target="_blank" style="color: #1976d2;">
                        Flair NER English Large Model ↗
                    </a>
                </li>
                <li><strong>spacy_en_core_web_trf:</strong> 
                    <a href="https://spacy.io/models/en#en_core_web_trf" target="_blank" style="color: #1976d2;">
                        spaCy English Transformer Model ↗
                    </a>
                </li>
                <li><strong>flair_ner-ontonotes-large:</strong> 
                    <a href="https://huggingface.co/flair/ner-english-ontonotes-large" target="_blank" style="color: #1976d2;">
                        Flair OntoNotes Large Model ↗
                    </a>
                </li>
                <li><strong>gliner_urchade/gliner_large-v2.1:</strong> 
                    <a href="https://github.com/urchade/GLiNER" target="_blank" style="color: #1976d2;">
                        GLiNER Extended Documentation ↗
                    </a>
                </li>
            </ul>
        </div>
        
       <br>
        <hr style="margin-top: 40px; margin-bottom: 20px;">
        <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin-top: 20px; text-align: center;">
            <p style="font-size: 14px; line-height: 1.8; margin: 0;">
                This <strong>Keyword Extraction Explorer Tool</strong> was created as part of the
                <a href="https://digitalscholarship.web.ox.ac.uk/" target="_blank" style="color: #1976d2;">Digital Scholarship at Oxford (DiSc)</a>
                funded research project: <em>Extracting Keywords from Crowdsourced Collections</em>.
            </p>
            <p style="font-size: 14px; line-height: 1.8; margin: 20px 0 0 0;">
                <strong>See also</strong> the main EKCC project repository:
                <a href="https://github.com/Digital-Scholarship-Oxford/crowdsourced-data-tools" target="_blank" style="color: #1976d2;">Crowdsourced Data Tools ↗</a>
            </p>
            <p style="font-size: 14px; line-height: 1.8; margin: 8px 0 0 0;">
                <strong>and</strong> Arana-Catania, M., Conisbee, C., &amp; Kidd, M. (2026).
                <em>Letting the Data Speak: Extracting Keywords from Crowdsourced Collections with AI.</em>
                <a href="https://doi.org/10.48550/arXiv.2607.09324" target="_blank" style="color: #1976d2;">https://doi.org/10.48550/arXiv.2607.09324 ↗</a>
            </p>
            <p style="font-size: 14px; line-height: 1.8; margin: 20px 0 0 0;">
                The code for this tool was built with the aid of Claude Opus 4 and updated with Opus 4.8.
            </p>
        </div>
        """)

    return demo

if __name__ == "__main__":
    demo = create_interface()
    demo.launch(server_name="0.0.0.0", server_port=7860)
    