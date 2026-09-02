class Constants:
    col_name: str = "method_type"
    tree: str = "Tree-based"
    foundational: str = "Foundation Model"
    neural_network: str ="Neural Network"
    baseline: str = "Baseline"
    # Whole pipelines rather than single models: AutoGluon, TabFM+, an agent, a hosted API.
    # Set upstream from MethodMetadata.method_class, never inferred from the name.
    system: str = "System"
    # Not Used
    other: str = "Other"

# Order here defines the display order of the type legend and filters.
model_type_emoji = {
    Constants.foundational: "🧠⚡",
    Constants.neural_network:"🧠🔁",
    Constants.tree: "🌳",
    Constants.baseline: "📏",
    # Not used
    Constants.other: "❓",
    Constants.system:"📊",
}

# Per-tag chip shown next to a system's name, from the `Tags` column of
# website_leaderboard.csv (MethodTag in tabarena/models/_method_metadata.py). Keys must match
# the tag strings that pipeline writes.
tag_emoji = {
    "with-llm": "🤖",
    "closed-source-api": "🔒",
}

tag_label = {
    "with-llm": "with LLMs",
    "closed-source-api": "closed-source API",
}

tag_tooltip = {
    "with-llm": (
        "An LLM is involved somewhere in this system, which may include an agent. Its results "
        "depend on a model whose training data we cannot inspect and which may already have "
        "seen the test data."
    ),
    "closed-source-api": (
        "This system runs behind a remote API we cannot inspect, and whose behaviour can change "
        "between runs."
    ),
}

# Per-variant accent color, taken from the interactive Leaderboard Overview
# explorer's --var-* (dark theme) so its variant toggles and the leaderboard
# table's agree. Keys must match views.VARIANT_VALUES.
variant_color = {
    "default": "#4386d5",
    "tuned": "#c05f38",
    "tuned + ensembled": "#289972",
}

# Per-type accent color (readable as text/border on the dark theme). Used for the
# type legend and to color-code model names in the cross-subset overview.
model_type_color = {
    Constants.foundational: "#b07cf0",  # purple
    Constants.neural_network: "#5aa9e6",  # blue
    Constants.tree: "#5cb85c",          # green
    Constants.baseline: "#9e9e9e",      # gray
    Constants.other: "#9e9e9e",         # gray
    Constants.system: "#f0a35a",        # orange
}
