"""
modules/workflow.py — How this tool is built

An in-app view that embeds the interactive data-to-decision workflow
(assets/figures/workflow.html) inside the application shell, in the app theme.
The workflow is self-contained; hovering traces the flow, clicking a stage opens
its detail, and "Run the pipeline" animates data end to end.
"""
from dash import html

MAROON = "#8C1D40"


def layout():
    return html.Div([
        html.Div([
            html.H2([html.I(className="bi bi-diagram-2",
                            style={"marginRight": "10px", "color": MAROON}),
                     "How this tool is built"]),
            html.P("An interactive map of the CRIA pipeline — from NASA and observational data, "
                   "through the cache and analytics, into the app and its outputs. Hover to trace "
                   "the flow, click any stage for detail, or run the pipeline end to end."),
        ], className="tab-header"),
        html.Div([
            html.Iframe(
                src="/assets/figures/workflow.html",
                style={"width": "100%", "height": "1040px", "border": "none",
                       "borderRadius": "12px", "background": "transparent"},
            ),
        ], className="tab-body"),
    ])


def register_callbacks(app):
    pass
