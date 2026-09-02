import json
from pathlib import Path
from django import forms

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "hugging_face.json"


class HuggingFaceFormFactory:
    @classmethod
    def create_form(cls, dataset_id: str, data: dict = None) -> forms.Form:
        with open(SCHEMA_PATH, "r") as f:
            schemas = json.load(f)

        if dataset_id not in schemas:
            raise ValueError(f"Schema for dataset '{dataset_id}' not found.")

        schema = schemas[dataset_id]
        fields = {}

        for field_name, spec in schema.items():
            field_type = spec["type"]
            default_val = spec.get("default")
            label = field_name.replace("_", " ").title()

            if field_type == "choice":
                fields[field_name] = forms.ChoiceField(
                    choices=spec.get("choices", []),
                    initial=default_val,
                    label=label
                )
            elif field_type == "char":
                fields[field_name] = forms.CharField(
                    initial=default_val,
                    label=label
                )

        form_class = type(f"HF_{dataset_id.replace('-', '_').title()}_Form", (forms.Form,), fields)
        return form_class(data=data)