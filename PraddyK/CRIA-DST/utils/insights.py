"""
utils/insights.py — one consistent interpretation panel for every analysis tab.

Each tab gets two short, honest sections:
  · "How to read this"   — describes what is actually on the screen (safe, data-descriptive)
  · "Why it matters"     — general water-management relevance of the variable/topic

IMPORTANT (scientific integrity): these are GENERAL hydrologic context, not recomputed
results. No fabricated statistics. Specific numbers live on the figures themselves, which
are computed live from the VIC reanalysis. Where a tab has its own richer built-in panel
(e.g. "Maps Over Time"), it is left out here to avoid duplication.
"""
from dash import html

MAROON = "#8C1D40"
BLUE = "#1565C0"

# view_key -> (how-to-read bullets, why-it-matters bullets)
INSIGHTS = {
    "home": (
        ["The overview stitches the whole basin together — pick any card to open the "
         "matching deep-dive analysis.",
         "Every figure in the app is computed live from the PRISM-calibrated VIC "
         "reanalysis (water years 1984–2024) unless a panel says otherwise."],
        ["A shared, consistent picture of basin conditions helps managers, tribes and "
         "the seven Basin states start from the same evidence.",
         "Use it as the entry point: confirm the current state here, then drill into the "
         "process (snow, soil, storage, drought) behind it."],
    ),
    "snowpack": (
        ["Blue/upper-elevation zones carry the deepest snow water equivalent (SWE); the "
         "curve shows how basin snowpack has moved year to year.",
         "Compare a high-snow year with a drought year to see how much runoff tracks the "
         "spring snowpack."],
        ["Mountain snowpack is the basin's largest natural reservoir — most Colorado "
         "River flow originates as high-elevation snowmelt.",
         "Snowpack size is the earliest signal water managers have for the coming runoff "
         "season and reservoir inflows."],
    ),
    "watbal": (
        ["Follow water in (precipitation) against water out (evapotranspiration, runoff, "
         "baseflow) to see where the basin's water goes.",
         "A widening gap between precipitation and streamflow points to more water being "
         "lost to the atmosphere and soils."],
        ["The water balance is the accounting behind supply: what actually reaches "
         "rivers and reservoirs after evaporation and soil demand.",
         "Rising evaporative losses under warming can shrink runoff even when "
         "precipitation holds steady — a core planning concern."],
    ),
    "timing": (
        ["This tracks WHEN snowmelt and peak flow arrive, not just how much — earlier "
         "dates shift the whole seasonal hydrograph.",
         "Watch the long-term drift toward earlier melt across the record."],
        ["Earlier melt lengthens the dry, high-demand summer and changes when reservoirs "
         "must capture inflow.",
         "Runoff timing drives reservoir operations, flood-control rules and irrigation "
         "scheduling."],
    ),
    "links": (
        ["Soil moisture is compared against streamflow response — dry soils absorb "
         "snowmelt before it can reach the river.",
         "Look for years where similar snowpack produced very different runoff; soil "
         "state is often the missing link."],
        ["Antecedent soil moisture is a leading reason runoff forecasts miss — it "
         "governs how much snowmelt becomes streamflow.",
         "Accounting for soil state improves seasonal water-supply outlooks."],
    ),
    "elevsnow": (
        ["Snow trends are split by elevation band — the mid-elevation rain–snow "
         "transition zone typically shows the steepest losses.",
         "Compare high peaks (more stable) with mid-slopes (most exposed to warming)."],
        ["Losses concentrate where warming pushes the snow line upward, so basin-average "
         "numbers hide where the real risk sits.",
         "Elevation-specific loss maps where future snowpack — and the water it stores — "
         "is most vulnerable."],
    ),
    "warming": (
        ["Surface temperature and the land energy balance are shown over time; warmer "
         "years raise atmospheric water demand.",
         "Read this alongside runoff: added energy tends to move water from streams to "
         "the atmosphere."],
        ["Temperature is the driver behind 'hot drought' — declining flows even in "
         "normal-precipitation years.",
         "Energy-balance trends explain why the basin can dry out without a rainfall "
         "deficit."],
    ),
    "tws": (
        ["GRACE satellite total water storage shows the whole water column — snow, soil, "
         "groundwater and surface water — gaining or losing mass.",
         "A steady downward slope means the basin is losing more water than it receives."],
        ["Total water storage is an independent, satellite-based check on the basin's "
         "long-term water debt.",
         "Persistent storage loss — especially groundwater — signals depletion that "
         "surface measurements alone can miss."],
    ),
    "storage": (
        ["This isolates subsurface storage (soil and groundwater) from the total, "
         "showing the slow-moving part of the system.",
         "Recovery here lags surface conditions — subsurface stores refill slowly."],
        ["Groundwater and deep soil storage are the buffer communities draw on when "
         "surface supply fails.",
         "Slow refill means multi-year droughts leave a lasting deficit even after a wet "
         "year."],
    ),
    "drought": (
        ["Drought and shortage indicators are tracked over the record; deeper/redder "
         "periods mark the most severe multi-year droughts.",
         "Compare the post-2000 period with earlier decades to judge how unusual recent "
         "conditions are."],
        ["Drought severity and duration drive the shortage tiers that determine "
         "delivery cuts across the Basin states.",
         "Distinguishing a dry spell from a sustained megadrought changes which "
         "management levers apply."],
    ),
    "cascade": (
        ["This follows drought as it propagates — from meteorological (precipitation) to "
         "soil moisture to hydrological (streamflow) drought.",
         "Note the lag: streamflow drought appears well after the rainfall deficit "
         "begins."],
        ["Propagation lags give managers lead time — a soil-moisture deficit today "
         "foreshadows a streamflow shortfall months ahead.",
         "Understanding the cascade helps target when interventions are still effective."],
    ),
    "recovery": (
        ["This examines how long the system takes to return to normal after drought, by "
         "compartment (soil, storage, flow).",
         "Repeated droughts before full recovery compound the deficit."],
        ["Recovery time sets how much wet-year runoff is needed to refill the system.",
         "Short gaps between droughts prevent full recovery and accelerate long-term "
         "decline."],
    ),
    "aridification": (
        ["This frames the long-term shift toward a drier baseline — a persistent trend, "
         "not a temporary drought.",
         "Read the slope over decades rather than any single year."],
        ["Aridification means the 'normal' the basin was allocated against is moving — "
         "planning to the old average overstates supply.",
         "A drier baseline reshapes every downstream decision, from allocations to "
         "reservoir targets."],
    ),
    "asi": (
        ["The Aridity Severity Index combines conditions into one comparable score; "
         "higher/redder means more severe aridity.",
         "Use it to rank years and periods on a common scale."],
        ["A single index makes basin-wide aridity easy to communicate to "
         "decision-makers and the public.",
         "Consistent scoring helps compare today's stress against the historical range."],
    ),
    "budyko": (
        ["The Budyko framework plots the water–energy balance: where a basin sits "
         "between water-limited and energy-limited behaviour.",
         "Movement toward the energy-limited/warm side over time indicates a drying, "
         "warming trajectory."],
        ["Budyko is a standard, physically-based way to separate how much drying comes from "
         "less water versus more atmospheric demand.",
         "It grounds the basin's changes in well-established hydrologic theory rather "
         "than a single statistic."],
    ),
    "future": (
        ["Projection curves extend conditions toward 2100 under different pathways; the "
         "spread between them is the uncertainty range.",
         "Read the range, not a single line — the envelope is the honest answer."],
        ["Long-horizon projections inform infrastructure and allocation decisions that "
         "last decades.",
         "Showing the full spread keeps planning robust to a range of plausible "
         "futures."],
    ),
    "noanalog": (
        ["This flags conditions with no match in the historical record — combinations "
         "the basin has not experienced before.",
         "Highlighted periods are where past-based expectations may break down."],
        ["No-analog conditions are where historical rules of thumb and stationarity "
         "assumptions fail.",
         "Identifying them early warns managers not to over-trust the historical "
         "baseline."],
    ),
    "nmme": (
        ["NMME seasonal forecasts show the coming-season outlook from a multi-model "
         "ensemble; the spread reflects forecast confidence.",
         "Treat the ensemble range as the forecast, not any single member."],
        ["Seasonal outlooks feed near-term reservoir operations and drought-response "
         "decisions.",
         "Ensemble spread communicates how much confidence to place in the outlook."],
    ),
    "cmip": (
        ["CMIP5/6 climate projections show the long-term climate envelope driving the "
         "basin; scenarios bracket plausible pathways.",
         "Compare scenarios rather than reading one as a prediction."],
        ["Global climate projections set the boundary conditions for basin water "
         "supply decades out.",
         "The scenario spread is essential context for any long-range plan."],
    ),
    "reservoirs": (
        ["Reservoir levels and the shortage tiers they trigger are shown together; "
         "crossing a tier line changes delivery rules.",
         "Read current storage against the tier thresholds, not just the raw elevation."],
        ["Lake Mead and Lake Powell elevations directly set legally binding shortage "
         "declarations and delivery cuts.",
         "Tier proximity is the single most watched operational signal in the basin."],
    ),
    "uncertainty": (
        ["This makes confidence explicit — ranges and intervals around the estimates, "
         "not just central values.",
         "Wider bands mean less certainty; narrow bands mean a robust signal."],
        ["Honest uncertainty is what makes a result usable for a real decision.",
         "Showing confidence lets managers weigh risk instead of over-trusting a single "
         "number."],
    ),
    "basinwide": (
        ["Every sub-basin is shown together and indexed to its own average, so basins of "
         "very different size are directly comparable.",
         "The spatial anomaly panel and the multi-basin chart tell the same story two "
         "ways."],
        ["Seeing all sub-basins at once shows where in the basin change is "
         "concentrated.",
         "The Upper Basin headwaters generate most flow, so their trajectory drives the "
         "whole system."],
    ),
    "animations": (
        ["Each animation plays the seasonal or year-to-year cycle, paired with its "
         "basin-average trend in a separate panel.",
         "Monthly animations show the within-year cycle; yearly ones show the long-term "
         "trajectory."],
        ["Watching water move through the year makes the timing of supply intuitive for "
         "non-specialists.",
         "Seasonal cycles are the backdrop against which drought and warming shift the "
         "system."],
    ),
    "spatcompare": (
        ["Freeze on one water year and compare two variables side by side, each with its "
         "sub-basin values and basin-average trend.",
         "Use the year slider to inspect a specific wet or drought year in detail."],
        ["Comparing variables for the same year reveals how snow, runoff and soil "
         "conditions line up spatially.",
         "Single-year snapshots are useful for post-event review and communication."],
    ),
}


def insights_panel(view):
    """Return a consistent interpretation panel for a view, or empty Div if none defined."""
    entry = INSIGHTS.get(view)
    if not entry:
        return html.Div()
    read_items, matter_items = entry

    def _col(title, icon_color, items):
        return html.Div([
            html.Div([
                html.I(className="bi bi-info-circle" if title.startswith("How")
                       else "bi bi-compass",
                       style={"marginRight": "8px", "color": icon_color}),
                html.Span(title, style={"fontWeight": "700"}),
            ], style={"marginBottom": "8px", "fontSize": "13px", "color": "#1e293b"}),
            html.Ul([html.Li(x, style={"marginBottom": "5px"}) for x in items],
                    style={"margin": "0", "paddingLeft": "20px", "fontSize": "12.5px",
                           "color": "#37474f", "lineHeight": "1.6"}),
        ], style={"flex": "1 1 320px", "minWidth": "280px"})

    return html.Div([
        html.Div([
            _col("How to read this", BLUE, read_items),
            _col("Why it matters for water management", MAROON, matter_items),
        ], style={"display": "flex", "flexWrap": "wrap", "gap": "24px",
                  "padding": "14px 18px"}),
        html.Div("General hydrologic context to aid interpretation — the figures above are "
                 "computed live from the VIC reanalysis; this panel is not a recomputed result.",
                 style={"fontSize": "10.5px", "color": "#78909c", "fontStyle": "italic",
                        "padding": "0 18px 12px"}),
    ], style={"background": "#f7fafc", "border": "1px solid #e2e8f0",
              "borderRadius": "8px", "marginTop": "18px"})
