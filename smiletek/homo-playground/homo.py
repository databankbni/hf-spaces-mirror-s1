class Homo:
    def __init__(self):
        # 1. Physical Layer
        self.gender = None
        self.age = None
        self.height = None
        self.weight = None
        self.ethnicity = None
        self.body_type = None
        self.appearance = {
            "face_shape": None,
            "hair_color": None,
            "eye_color": None,
            "skin_tone": None,
            "unique_marks": []
        }
        self.voice = {
            "timbre": None,
            "pitch": None,
            "range": None,
            "speed": None,
            "accent": None
        }
        self.physical_abilities = {
            "strength": 0,
            "endurance": 0,
            "agility": 0,
            "reaction_speed": 0,
            "health": 100
        }

        # 2. Sensory Layer
        self.senses = {
            "vision": None,
            "hearing": None,
            "smell": None,
            "taste": None,
            "touch": None,
            "interoception": None
        }

        # 3. Cognitive Layer
        self.cognition = {
            "intelligence": {
                "logic": 0,
                "memory": 0,
                "creativity": 0,
                "learning_speed": 0
            },
            "emotions": {
                "recognition": 0,
                "expression": 0,
                "regulation": 0
            },
            "personality": {
                "extraversion": 0,
                "openness": 0,
                "conscientiousness": 0,
                "agreeableness": 0,
                "neuroticism": 0
            },
            "values": {
                "morality": None,
                "politics": None,
                "religion": None,
                "life_goals": []
            },
            "habits": {
                "food_preferences": [],
                "hobbies": [],
                "routines": []
            }
        }

        # 4. Behavioral Layer
        self.behavior = {
            "language": {
                "native": None,
                "foreign": [],
                "vocabulary_size": 0,
                "style": None
            },
            "social": {
                "empathy": 0,
                "communication": 0,
                "leadership": 0,
                "cooperation": 0
            },
            "decision_making": {
                "impulsiveness": 0,
                "risk_taking": 0,
                "problem_solving": 0
            },
            "skills": {
                "professional": [],
                "life": [],
                "sports": []
            }
        }

        # 5. Social Layer
        self.social = {
            "family": [],
            "nationality": None,
            "occupation": None,
            "education": None,
            "status": None,
            "social_network": []
        }

        # 6. Dynamic Dimensions
        self.state = {
            "current_emotion": None,
            "current_health": 100,
            "current_energy": 100,
            "knowledge": [],
            "relationships": {},
            "environment": {
                "location": None,
                "weather": None,
                "economy": None,
                "politics": None
            }
        }