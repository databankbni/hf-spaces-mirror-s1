"""
utils/components.py
===================
Shared UI helper functions used across modules.
"""

from dash import html
import dash_bootstrap_components as dbc


def info_tile(value, label, icon="", color="tile-navy"):
    """Reusable info metric tile (same as CRB-WRDST tiles)."""
    return html.Div([
        html.Div(str(value), className="info-tile-value"),
        html.Div(label, className="info-tile-label"),
        html.Div(icon, className="info-tile-icon"),
    ], className=f"info-tile {color}")


def crb_card(title, children, className="", id=None):
    """Styled card wrapper matching .crb-card CSS class."""
    kwargs = {"className": f"crb-card {className}"}
    if id:
        kwargs["id"] = id
    return html.Div([
        html.Div(title, className="crb-card-header") if title else html.Div(),
        html.Div(children, className="crb-card-body"),
    ], **kwargs)


def control_row(*controls):
    """Horizontal row of controls inside a .control-panel div."""
    return html.Div(
        dbc.Row([dbc.Col(c, xs=12, md="auto") for c in controls], className="g-2 align-items-end"),
        className="control-panel mb-3",
    )


def findings_bar(text):
    """Green 'key findings' banner bar."""
    return html.Div([
        html.Span("▸ ", style={"fontWeight": "800", "color": "#2E7D32"}),
        html.Span(text),
    ], style={
        "background": "#e8f5e9",
        "border": "1px solid #a5d6a7",
        "borderRadius": "6px",
        "padding": "10px 16px",
        "fontSize": "13px",
        "color": "#1B5E20",
        "marginBottom": "16px",
    })


def xref(intro, links):
    """A compact 'related analyses' cross-reference strip.
    intro: short lead text · links: list of (label, href) tuples."""
    children = [html.I(className="bi bi-signpost-split",
                       style={"marginRight": "7px", "color": "#8C1D40"}),
                html.Span(intro, style={"fontWeight": "700", "color": "#0D2137"})]
    for i, (label, href) in enumerate(links):
        children.append(html.Span(" · " if i else "  ", style={"color": "#94a3b8"}))
        children.append(html.A(label, href=href,
                               style={"color": "#01579B", "fontWeight": "600",
                                      "textDecoration": "none"}))
    return html.Div(children, style={
        "background": "#f1f5f9", "borderLeft": "3px solid #8C1D40",
        "borderRadius": "0 6px 6px 0", "padding": "9px 14px",
        "fontSize": "11.5px", "lineHeight": "1.5", "marginTop": "12px"})


def info_dot(children, width="300px"):
    """A small maroon ⓘ icon; click to reveal an explanation popover.
    `children` may be a string or a list of Dash components."""
    return html.Details([
        html.Summary("ⓘ", style={"color": "#8C1D40", "cursor": "pointer",
                                  "fontSize": "13px", "fontWeight": "800",
                                  "display": "inline-block"}),
        html.Div(children, style={"position": "absolute", "zIndex": 5000,
            "background": "#fffdf2", "border": "1px solid #ffe39a",
            "borderLeft": "3px solid #8C1D40", "borderRadius": "0 6px 6px 0",
            "padding": "9px 12px", "fontSize": "11px", "lineHeight": "1.5",
            "color": "#37474f", "maxWidth": width, "marginTop": "3px",
            "boxShadow": "0 4px 14px rgba(13,33,55,0.14)"}),
    ], className="info-dot", style={"display": "inline-block", "position": "relative",
                                    "marginLeft": "6px", "verticalAlign": "middle"})


def howto(text):
    """A compact, stakeholder-friendly 'How to read this' guidance strip for a tab."""
    return html.Div([
        html.I(className="bi bi-compass", style={"marginRight": "7px", "color": "#8C1D40"}),
        html.B("Guide:  "),
        text,
    ], className="howto-strip")


def pub_author(label, url, citation, status="published"):
    """A yellow-star author-attribution badge placed directly under a key finding,
    crediting the published work this finding matches (e.g. 'Whitney et al. — published').

    Spacing uses the flex container's `gap` — never trailing/leading spaces inside the
    spans — so the words can never run together (flex trims edge whitespace, which used
    to render 'This finding isCastle 2014'). The status shows as a small pill: a green
    check for genuinely published work, a muted amber tag for related/observational
    context (so an 'observational here' note is never dressed up as 'published')."""
    is_pub = str(status).strip().lower().startswith("publish")
    pill_common = {"display": "inline-flex", "alignItems": "center", "verticalAlign": "middle",
                   "borderRadius": "20px", "padding": "1px 9px", "fontSize": "10px",
                   "fontWeight": "800", "whiteSpace": "nowrap", "marginLeft": "3px"}
    if is_pub:
        pill = html.Span(
            [html.I(className="bi bi-patch-check-fill",
                    style={"fontSize": "10px", "marginRight": "4px"}), "published"],
            style={**pill_common, "background": "#e9f7ee", "color": "#1f7a3d",
                   "border": "1px solid #bfe6cd", "letterSpacing": ".2px"})
    else:
        pill = html.Span(
            status,
            style={**pill_common, "background": "#fff7e6", "color": "#9a6a00",
                   "border": "1px solid #f0d489"})
    # Inline flow (not flexbox): real spaces inside the spans are preserved both visually
    # AND in the text layer, so copy-paste / screen readers read "This finding is Castle …"
    # correctly. verticalAlign keeps the star, text, link and pill on one line.
    return html.Div([
        html.I(className="bi bi-star-fill",
               style={"color": "#FFC627", "fontSize": "13px",
                      "verticalAlign": "middle", "marginRight": "5px"}),
        html.Span("This finding is ",
                  style={"fontSize": "11px", "color": "#475569", "verticalAlign": "middle"}),
        html.A(label, href=url, target="_blank", title=f"Already in the literature: {citation}",
               style={"color": "#0D2137", "fontWeight": "700", "fontSize": "11px",
                      "textDecoration": "underline", "textUnderlineOffset": "2px",
                      "verticalAlign": "middle"}),
        " ",   # real space so copy-paste / screen readers read "… 2025 published"
        pill,
    ], style={"marginTop": "-6px", "marginBottom": "12px", "paddingLeft": "4px",
              "lineHeight": "1.9"})


def pub_star(url, citation, label="Published"):
    """A compact yellow-star badge placed directly on a chart title / tile / finding,
    linking to the paper that already published this result. Hover shows the citation."""
    return html.A([html.I(className="bi bi-star-fill", style={"color": "#FFC627", "marginRight": "4px"}), label],
                  href=url, target="_blank", title=f"Already published in: {citation}",
                  style={"fontSize": "10px", "fontWeight": "700", "color": "#b0792b",
                         "background": "#fffdf2", "border": "1px solid #ffe39a",
                         "borderRadius": "10px", "padding": "1px 8px", "marginLeft": "8px",
                         "textDecoration": "none", "whiteSpace": "nowrap"})


def pub_evidence(refs, note="Published evidence"):
    """A yellow-star provenance strip linking results to the paper(s) that already
    published this finding/data. refs: list of (label, url) tuples."""
    children = [html.I(className="bi bi-star-fill", style={"color": "#FFC627", "fontSize": "14px",
                                            "marginRight": "6px"}),
                html.Span(f"{note}: ", style={"fontWeight": "700", "fontSize": "11px",
                                              "color": "#0D2137"})]
    for i, (label, url) in enumerate(refs):
        if i:
            children.append(html.Span(" · ", style={"color": "#b0792b"}))
        children.append(html.A(label, href=url, target="_blank",
                               style={"color": "#01579B", "fontWeight": "600",
                                      "fontSize": "11px", "textDecoration": "none"}))
    return html.Div(children, style={
        "background": "#fffdf2", "border": "1px solid #ffe39a",
        "borderLeft": "3px solid #FFC627", "borderRadius": "0 6px 6px 0",
        "padding": "7px 12px", "marginBottom": "10px",
        "display": "flex", "alignItems": "center", "flexWrap": "wrap", "gap": "2px"})


def empty_fig(message="Run preprocessing scripts first (see SETUP.md)"):
    """Placeholder figure when data cache doesn't exist yet."""
    import plotly.graph_objects as go
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper", yref="paper",
        x=0.5, y=0.5,
        showarrow=False,
        font=dict(size=14, color="#666"),
    )
    fig.update_layout(
        paper_bgcolor="white",
        plot_bgcolor="white",
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        margin=dict(l=20, r=20, t=20, b=20),
        height=300,
    )
    return fig
