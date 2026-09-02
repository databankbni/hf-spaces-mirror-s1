---
title: Homo
emoji: 🧬
colorFrom: indigo
colorTo: purple
sdk: static
pinned: false
license: apache-2.0
short_description: Model a human being as structured data across six layers
tags:
  - human-modeling
  - data-model
  - simulation
  - pyodide
---

# Homo — A Human Modeling Framework

**Homo** (from Latin *human*) is a conceptual and programmatic framework for modeling human beings as structured data.
It provides a layered model that captures physical, cognitive, social, and dynamic aspects of a person.

This Space is an interactive playground for the model. Adjust the parameters on the left and the
corresponding `Homo` instance is rebuilt on the right. `homo.py` runs directly in your browser
via Pyodide — there is no server, and nothing you enter leaves your machine.

## Layers of the Homo Model

### 1. Physical Layer (Body Parameters)
- **Basic Bio Info**: gender, age, height, weight, body type, ethnicity/skin color
- **Appearance**: face shape, facial proportions, hair color, eye color, hairstyle, skin texture, unique marks (birthmarks, scars, tattoos)
- **Body Functions**: strength, endurance, agility, flexibility, reaction speed, immunity, health condition
- **Voice Features**: timbre, pitch, vocal range, speech rate, accent, intonation patterns

### 2. Sensory Layer (Input Channels)
- **Vision**: eyesight, color recognition, spatial awareness
- **Hearing**: hearing range, pitch sensitivity
- **Smell**: sensitivity, odor memory
- **Taste**: intensity, preferences
- **Touch**: pain threshold, sensitivity
- **Interoception**: hunger, thirst, balance, fatigue perception

### 3. Cognitive Layer (Thinking & Intelligence)
- **Intelligence Structure**: logic, abstract reasoning, memory capacity, learning speed, creativity
- **Emotional System**: emotion recognition, expression, regulation
- **Personality Traits**: extraversion/introversion, openness, conscientiousness, agreeableness, neuroticism (Big Five)
- **Values & Beliefs**: morality, political stance, religion, life goals
- **Habits & Preferences**: food preferences, hobbies, routines

### 4. Behavioral Layer (Output & Actions)
- **Language Ability**: native language, foreign languages, vocabulary size, expression style, writing skills
- **Social Skills**: empathy, communication, leadership, cooperation
- **Decision-Making**: impulsiveness, risk tolerance, problem-solving style
- **Skills**: professional (e.g., programming, medicine), life (e.g., cooking, driving), sports

### 5. Social Layer (Relations & Identity)
- **Family Background**: parents, siblings, intimate relationships
- **Social Identity**: nationality, occupation, education, social status
- **Network Relations**: number of friends, social circles, social media presence
- **Cultural Background**: native culture, cultural influences

### 6. Dynamic Dimensions (Variable Parameters)
- **Emotional State**: current happiness, anxiety, anger levels
- **Health State**: sleep, diet, illness, energy levels
- **Knowledge State**: newly learned knowledge, forgotten knowledge
- **Relationship State**: relationship status, social closeness changes
- **Environmental Influence**: location, weather, economy, political environment

## Usage

```python
from homo import Homo

person = Homo()
person.age = 30
person.cognition["personality"]["openness"] = 82
person.state["current_emotion"] = "focused"
```

## Files

| File | Purpose |
| --- | --- |
| `homo.py` | The framework itself — pure Python, standard library only |
| `index.html` | The playground UI, loading `homo.py` through Pyodide |

## License

[Apache-2.0 License](LICENSE), Smiletek Limited