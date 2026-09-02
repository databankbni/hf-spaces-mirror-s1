#!/usr/bin/env python3
"""
Script to generate a static plot identical to the KVPress leaderboard plot and save it as a PNG image.
"""

import sys
from pathlib import Path

from src.data import filter_dataframe, load_evaluation_results
from src.settings import (
    LB_ALLOWED_DATASETS,
    LB_ALLOWED_MODELS,
    LB_DEFAULT_MODELS,
    LOCAL_RESULTS_DIR,
)
from src.utils import create_interactive_leaderboard_plot


def generate_static_plot(output_path: str = "kvpress_leaderboard.png"):
    """
    Generate a static plot identical to the leaderboard plot and save it as a PNG image.

    Parameters
    ----------
    output_path : str
        Path where to save the PNG image
    width : int
        Width of the output image in pixels
    height : int
        Height of the output image in pixels
    """
    print("Loading results...")

    # Load dataframe file with results (same as in app.py)
    results_df = load_evaluation_results(LOCAL_RESULTS_DIR, pretty_method_names=True)

    # Filter the dataframe according to the settings in settings.py (same as in app.py)
    results_df = filter_dataframe(results_df, selected_datasets=LB_ALLOWED_DATASETS, selected_models=LB_ALLOWED_MODELS)

    # Get default models for initial display (same as in app.py)
    default_models = LB_DEFAULT_MODELS or LB_ALLOWED_MODELS

    print("Creating plot...")

    # Filter dataframe for plot display using default models (same as in app.py)
    plot_df = filter_dataframe(results_df, selected_models=default_models)

    # Get all methods for consistent color assignment
    all_methods = sorted([m for m in results_df["method"].unique() if m != "No Compression"])

    # Create the plot using the same function as the leaderboard
    fig = create_interactive_leaderboard_plot(plot_df, title="KVPress Leaderboard", all_methods=all_methods)

    # make the labels and legend bigger, also the axis labels
    fig.update_layout(
        font=dict(size=16),
        legend=dict(font=dict(size=16)),
        xaxis=dict(title_font_size=16, tickfont_size=14),
        yaxis=dict(title_font_size=16, tickfont_size=14),
    )

    # Remove title for PNG version
    fig.update_layout(title=None)

    fig.update_layout(
        legend=dict(orientation="h", yanchor="bottom", y=-0.25, xanchor="center", x=0.5, title=None),
        xaxis=dict(
            title_font_size=18,
            title_font=dict(weight="bold"),
            tickfont_size=15,
            showgrid=True,
            gridwidth=1,
            gridcolor="lightgray",
        ),
        yaxis=dict(
            title_font_size=18,
            title_font=dict(weight="bold"),
            tickfont_size=15,
            showgrid=True,
            gridwidth=1,
            gridcolor="lightgray",
        ),
        title_font_size=30,
        plot_bgcolor="white",
        height=600,
        title=dict(
            text="🏆 <b>KV Cache Compression Leaderboard</b> 🏆",  # Using unicode stars
            x=0.5,
            font=dict(
                family="Segoe UI, sans-serif",  # A common system font that supports emojis well
                size=32,
                color="black",  # A medium purple
            ),
        ),
    )

    # make layout more compact
    fig.update_layout(
        margin=dict(l=10, r=10, t=20, b=10),
    )

    # Save the PNG file
    # high quality
    fig.write_image(output_path, width=1200, height=800, scale=3)
    print(f"Plot saved as PNG: {output_path}")

    print(f"Plot saved successfully to {output_path}")


def main():
    """Main function to run the static plot generation."""
    # Default output path
    output_path = "kvpress_leaderboard.png"

    # Check if output path is provided as command line argument
    if len(sys.argv) > 1:
        output_path = sys.argv[1]

    # Ensure the output directory exists
    output_dir = Path(output_path).parent
    if output_dir != Path("."):
        output_dir.mkdir(parents=True, exist_ok=True)

    try:
        generate_static_plot(output_path=output_path)
    except Exception as e:
        print(f"Error generating plot: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
