"""
modules/why.py — dedicated "Why CRIA" page.

Opens as its own route (/why) from the floating "Why CRIA" pill, the same way
"How This Tool Is Built" opens at /workflow. The content (audience, the gap it
fills, what's novel, and how it differs from the CRB Scenario-Explorer) is built
by home._why_cria() so there is a single source of truth.
"""
from dash import html
from modules.home import _why_cria


def layout():
    return html.Div([
        html.Div([
            _why_cria(),
        ], className="tab-body"),
    ])
