import hvplot.pandas
import numpy as np
import pandas as pd
import panel as pn
import param
import xarray as xr
import geopandas as gpd
import cartopy.crs as ccrs
from bokeh.models import HoverTool, LegendItem
from bokeh.plotting import figure as bokeh_figure
from shapely.geometry import Polygon, GeometryCollection
import holoviews as hv
from holoviews import streams
from holoviews import streams
import geoviews.feature as gf
import geoviews as gv  # Import for Graticule
from functools import lru_cache
import glob
from bokeh.models.dom import HTML
import tooltips_strings
from pathlib import Path

# Custom CSS to highlight the active tab background
# Targeting multiple potential DOM structures for robustness
active_tab_css = """
/* Make all tabs a little larger and give inactive tabs a visible border */
.bk-tab,
.mdc-tab {
    padding: 8px 14px !important;
    min-height: 38px !important;
    border: 1px solid #bfc7d5 !important;
    border-bottom: 0 !important;
    border-radius: 8px 8px 0 0 !important;
    margin-right: 4px !important;
}

.bk-tab .bk-tab-text,
.mdc-tab__text-label {
    font-size: 14px !important;
    line-height: 1.2 !important;
}

/* Standard Bokeh/Panel structure */
.bk-tab.bk-active {
    background-color: #2196f3 !important;
    color: white !important;
    font-weight: bold !important;
    border-color: #2196f3 !important;
}

/* Material Design specific overrides if needed */
.mdc-tab--active .mdc-tab__text-label {
    color: white !important;
    font-weight: bold !important;
}

/* Ensure container header background is consistent */
.bk-tabs-header .bk-tab.bk-active {
    background-color: #2196f3 !important;
}

.bk-tabs-header,
.bk-tab-list,
.mdc-tab-bar {
    border-bottom: 1px solid #bfc7d5 !important;
}
"""
# Configure global loading indicator
pn.config.loading_spinner = 'arc'
pn.config.loading_color = '#333333'

pn.extension(design="material", sizing_mode="stretch_width", raw_css=[active_tab_css])


def get_data():
    gdf_regions = gpd.read_file('data/aux/rainfall_regions.geojson',).set_index('index')
    gdf_regions = gdf_regions.reset_index()
    dummy_polygon = Polygon([
        (0, -80),
        (1, -80),
        (1, -79),
        (0, -79)
    ])
    gdf_regions.loc[1 - 0.5] = ["Region 2", dummy_polygon]  # temporary fractional index
    gdf_regions = gdf_regions.sort_index().reset_index(drop=True)
    gdf_regions = gdf_regions.set_index("index")
    region_names = gdf_regions.index.values
    
    def process_csv(path):
        filename = path.split('/')[-1]
        is_mpi_or_cesm2 = ('MPI' in filename) #or ('CESM2' in filename)

        # Read CSV and drop an unnamed index column when present.
        df = pd.read_csv(path)
        if len(df.columns) > 0 and (str(df.columns[0]).startswith('Unnamed') or str(df.columns[0]) == ''):
            df = df.iloc[:, 1:]

        # Some non-MPI/CESM2 files include an extra "member" column even in ensemble_mean.
        # Drop it there to keep dimensions consistent with downstream logic.
        if (not is_mpi_or_cesm2) and ('data/results/ensemble_mean/' in path) and ('member' in df.columns):
            df = df.drop(columns=['member'])

        # Map source names
        mapping = {'conversion': 'Conversion', 'dynamical': 'Dynamical', 'nonlinear': 'Non Linear'}
        df['source'] = df['source'].map(mapping).fillna(df['source'])
        # Map region_id (1-based index) to region names
        df['region_id'] = df['region_id'].apply(lambda x: region_names[x-1] if 0 < x <= len(region_names) else 'Unknown')
        
        # Determine pivot columns (member exists in ensemble file)
        pivot_cols = ['model', 'season', 'region_id', 'source', 'term']
        if 'member' in df.columns:
            pivot_cols.append('member')
            
        # Convert to Xarray
        obj = df.set_index(pivot_cols)['value'].to_xarray()
        
        # Ensure region order matches GeoJSON to prevent mapping bugs
        if 'region_id' in obj.coords:
            obj = obj.reindex(region_id=region_names)
        
        # Scale units (new CSV data is already aggregated but needs % scaling to match 100% total roughly)
        obj = obj / 0.05*100
        
        # Replace zeros with NaN so they are greyed out in plots
        obj = obj.where(obj != 0)
        
        return obj

    list_ensemble_mean_files = glob.glob("data/results/ensemble_mean/*.csv")
    list_ensemble_members_files = glob.glob("data/results/ensemble/*/*.csv")
    # print(f"Found ensemble mean files: {len(list_ensemble_mean_files)}")
    # print(f"Found ensemble member files: {len(list_ensemble_members_files)}")
    # Combine ensemble mean files by model
    data_ensemble_mean = xr.concat([process_csv(f) for f in list_ensemble_mean_files], dim='model', join='outer')
    # Combine ensemble member files by model (member dimension handled in process_csv)
    models = [f.split('/')[-1].split('_')[0] for f in list_ensemble_members_files]
    models = np.unique(models)
    all_data_models = []
    for model in models:
        data_ensemble_model = xr.concat([process_csv(f) for f in list_ensemble_members_files if model in f], dim='member', join='outer')
        all_data_models.append(data_ensemble_model)
    data_ensemble_members = xr.concat(all_data_models, dim='model', join='outer')
    data_ensemble_mean = data_ensemble_mean.reindex(region_id=region_names)
    data_ensemble_members = data_ensemble_members.reindex(region_id=region_names)
    # data_ensemble_members = data_ensemble_members.where(data_ensemble_members!=0.0)
    # Load precursor pattern GeoJSONs for each variable
    gdf_precursors_u850 = gpd.read_file('data/aux/precursor_patterns_U850.json')
    gdf_precursors_v850 = gpd.read_file('data/aux/precursor_patterns_V850.json')
    gdf_precursors_z500 = gpd.read_file('data/aux/precursor_patterns_Z500.json')
    
    return data_ensemble_mean, data_ensemble_members, gdf_regions, gdf_precursors_u850, gdf_precursors_v850, gdf_precursors_z500


data_ensemble_mean, data_ensemble_members, gdf_regions, gdf_precursors_u850, gdf_precursors_v850, gdf_precursors_z500 = get_data()

def get_cached_precursor_map(variable_name, season, region, vmax):
    """Cached version of precursor map plotting."""
    if variable_name == 'U850':
        gdf = gdf_precursors_u850
    elif variable_name == 'V850':
        gdf = gdf_precursors_v850
    elif variable_name == 'Z500':
        gdf = gdf_precursors_z500
    else:
        return None
        
    filtered = gdf.query("season==@season & region==@region")
    if len(filtered) == 0:
        return pn.pane.Markdown(f"No data for {region} in {season}")
    
    plot_bounds = filtered.total_bounds
    xlim = (plot_bounds[0], plot_bounds[2])
    ylim = (plot_bounds[1], plot_bounds[3])
    
    unit = 'm²/s²' if variable_name == 'Z500' else 'm/s'
    hover = HoverTool(tooltips=[
        (f"{variable_name} anomaly", f"@variable_level{{0.0}} {unit}")
    ])
    
    plot = (filtered.hvplot.polygons(
        crs=ccrs.PlateCarree(), 
        color='variable_level',
        cmap='RdBu_r',
        colorbar=False,
        clim=(-vmax, vmax),
        projection=ccrs.PlateCarree(),
        line_width=0,
        # projection=ccrs.PlateCarree(),
        xlim=xlim,
        ylim=ylim,
        # frame_width=300,
        # frame_height=300,
        responsive=True,
        # aspect=0.75,
        tools=[hover],
        title=variable_name + f" ({season})"
    ) * gf.coastline * gf.grid()).opts(
        axiswise=True
    )

    return plot

def get_precursor_plot(season='SON', region='Egypt + East Libya'):
    """Get all three precursor maps side-by-side."""
    u850_map = pn.Column(get_cached_precursor_map('U850', season, region, 10), sizing_mode='scale_width', margin=(0, 0, 10, 0), max_width=400)
    v850_map = pn.Column(get_cached_precursor_map('V850', season, region, 10), sizing_mode='scale_width', margin=(0, 0, 10, 0), max_width=400)
    z500_map = pn.Column(get_cached_precursor_map('Z500', season, region, 2000), sizing_mode='scale_width', margin=(0, 0, 10, 0), max_width=400)
    
    try:
        # Use pn.Row for robust handling of independent Geo plots
        return pn.Row(u850_map, 
                      v850_map, 
                      z500_map, 
                      sizing_mode='scale_width', 
                      max_width=1200)
    except Exception as e:
        print(f"Error in get_precursor_plot composition: {e}")
        import traceback
        traceback.print_exc()
        return pn.pane.Markdown(f"**Error** plotting precursors: {e}", sizing_mode='scale_width')


# OPTIMIZATION 1: Cache the expensive classification computation
@lru_cache(maxsize=256)
def compute_classified_data_v3(model, season, term, nonlinear_pos, source_tuple, min_bias=20, slope_val=0.2):
    """Computation of classified data with dynamic thresholds - CACHED VERSION."""
    # 1. Select data components for all regions
    try:
        ds_model = data_ensemble_mean.sel(model=model, season=season, term=term).squeeze()
    except Exception:
        # Return empty DataFrame if selection fails
        return pd.DataFrame(columns=['Region', 'Conversion', 'Dynamical', 'Non_Linear', 'X', 'Y', 'Selected_Sum', 'Net apparent', 'Type', 'Text_Color'])
    
    # 2. Extract base components (keep NaN instead of filling)
    conversion = ds_model.sel(source='Conversion')
    dynamical = ds_model.sel(source='Dynamical')
    nonlinear = ds_model.sel(source='Non Linear')
    
    # 3. Determine X and Y for classification (based on nonlinear_pos setting)
    if nonlinear_pos == 'Dynamical':
        x_val = conversion
        y_val = dynamical + nonlinear
    else:
        x_val = conversion + nonlinear
        y_val = dynamical
        
    # 4. Create DataFrame (keep NaN values)
    # ds_model.sel(source=list(source_tuple)) works because xarray handles lists
    df = pd.DataFrame({
        'Region': ds_model.region_id.values,
        'Conversion': conversion.values,
        'Dynamical': dynamical.values,
        'Non_Linear': nonlinear.values,
        'X': x_val.values,
        'Y': y_val.values,
        'Selected_Sum': ds_model.sel(source=list(source_tuple)).sum('source', min_count=1).values if source_tuple else 0,
        'Net apparent': (conversion + dynamical + nonlinear).values
    })
    
    # 5. Add classification logic
    def classify(row):
        x, y = row['X'], row['Y']
        # If either X or Y is NaN, return NaN (this will filter them out from scatter)
        if pd.isna(x) or pd.isna(y):
            return np.nan
        if abs(x) + abs(y) <= min_bias: return 'Minimal'
        if abs(x) < slope_val * abs(y): return 'Dynamical'
        if abs(y) < slope_val * abs(x): return 'Conversion'
        return 'Compounding' if x * y > 0 else 'Compensating'
        
    df['Type'] = df.apply(classify, axis=1)
    
    # 6. Saturated colors for readable hover text
    text_cmap = {
        'Minimal': '#1B5E20', # Dark Green
        'Conversion': '#B8860B', # Dark Gold
        'Dynamical': '#0277BD',  # Dark Blue
        'Compounding': '#7B1FA2', # Dark Purple
        'Compensating': '#E65100',   # Dark Orange
        'No Data': '#D3D3D3'  # Light Grey for missing data
    }
    df['Text_Color'] = df['Type'].map(text_cmap)
    df['Text_Color'] = df['Text_Color'].fillna('#D3D3D3')
    
    return df


class CMIPApp(param.Parameterized):
    model = param.Selector(default='CESM2' if 'CESM2' in data_ensemble_mean.model.values else list(data_ensemble_mean.model.values)[0], 
                           objects=list(np.sort(data_ensemble_mean.model.values)), label="Choose a climate model:")
    model_a = param.Selector(
        default='NorESM2-LM' if 'NorESM2-LM' in data_ensemble_mean.model.values else list(data_ensemble_mean.model.values)[0],
        objects=list(np.sort(data_ensemble_mean.model.values)),
        label="Model A:")
    model_b = param.Selector(
        default='NorESM2-MM' if 'NorESM2-MM' in data_ensemble_mean.model.values else list(data_ensemble_mean.model.values)[-1],
        objects=list(np.sort(data_ensemble_mean.model.values)),
        label="Model B:")
    selected_models = param.ListSelector(default=list(data_ensemble_mean.model.values), objects=list(np.sort(data_ensemble_mean.model.values)), label="Models to include")
    season = param.Selector(default='DJF', objects=['DJF', 'MAM', 'JJA', 'SON'], label="Choose a season:")
    term = param.Selector(default='bias', label='Choose a metric:', objects={'Bias (vs ERA5, 1979-2014)': 'bias', 
                                                                            'Change (2065-2100 vs 1979-2014)': 'change', 
                                                                            'Uncalibrated Change (2065-2100 vs 1979-2014)': 'uncalibrated_change'})
    source = param.ListSelector(default=['Conversion','Dynamical','Non Linear'], objects=['Dynamical', 'Conversion', 'Non Linear'], label=f'Source of bias/change to plot')
    nonlinear_pos = param.Selector(default='Dynamical', objects=['Dynamical', 'Conversion'], label="Group non-linear term with:")
    vmax = param.Integer(default=100, bounds=(1, 200), label="Colorbar limits (%)")
    min_bias_threshold = param.Number(default=20, bounds=(1, 100), label=f"Minimal difference threshold (%)")
    slope_control = param.Number(default=0.2, bounds=(0.01, 0.5), label="Sector slope threshold (ratio)")
    
    # Toggle for ensemble members in multi-model tab
    show_ensemble_members = param.Boolean(default=True, label="Show Ensemble Members")

    # Bar plot sorting
    bar_sort = param.Selector(default='Net apparent', objects=['Net apparent', 'Conversion', 'Dynamical', 'Non_Linear'], label="Sort bars by:")
    bar_sort_ascending = param.Boolean(default=True, label="Ascending")

    # Interval (percent) between diagonal constant-apparent-bias lines
    diag_interval = param.Integer(default=20, bounds=(1, 100), label="Constant apparent bias every (%)")
    show_diag_lines = param.Boolean(default=True, label="Show apparent bias lines")
    show_diamonds = param.Boolean(default=False, label="Show total bias diamonds")
    

    # Master selection state
    _selection_index = param.List(default=[])
    # Track when sync is in progress for loading indicator
    _is_syncing = param.Boolean(default=False)
    # User-facing region selector for sidebar
    selected_regions = param.ListSelector(default=[], objects=[ k for k in list(gdf_regions.sort_index().index) if 'Region 2' not in k], label="Selected Regions")
    # Toggle for performance-intensive precursor maps
    show_precursors = param.Boolean(default=False, label="Show Precursor Maps (Slower)",)
    
    # Shared color map for sectors
    sector_cmap = {
        'Minimal': '#7af9ab', # Pale Green
        'Conversion': '#e2ca76', # Pale Yellow
        'Dynamical': '#b1d1fc',  # Pale Blue
        'Compounding': '#c5b5d4', # Pale Purple
        'Compensating': '#de7f8b',   # Pale Orange
        'No Data': '#D3D3D3'  # Light Grey for missing data
    }
        
    def __init__(self, **params):
        super().__init__(**params)
        # Separate streams for each view to prevent source-swapping issues
        self.v_map_s = streams.Selection1D()
        self.t_map_s = streams.Selection1D()
        self.scat_s = streams.Selection1D()
        self.sel_map_s = streams.Selection1D()

        # Shared map range for linked axes
        self.map_r = streams.RangeXY()
        # scatter range stream was removed; it caused unwanted autoscale on selection
        
        # Link map streams to update the master selection
        self.v_map_s.param.watch(self._sync_selection, 'index')
        self.t_map_s.param.watch(self._sync_selection, 'index')
        self.sel_map_s.param.watch(self._sync_selection, 'index')
        # Scatter stream needs special handling: convert scatter positions to region names
        self.scat_s.param.watch(self._sync_selection_from_scatter, 'index')
        
        # Link sidebar region selector to selection index
        self.param.watch(self._sync_from_sidebar, 'selected_regions')
        self.param.watch(self._sync_to_sidebar, '_selection_index')
        
        # Ensure initial selector state matches data
        self.param.selected_models.objects = list(np.sort(data_ensemble_mean.model.values))
        self.param.model.objects = list(np.sort(data_ensemble_mean.model.values))

        # To share actual Bokeh range objects for linked axes across tabs
        self._shared_x_range = None
        self._shared_y_range = None
        
        # OPTIMIZATION 2: Cache the full classified dataframe
        self._cached_classified_data = None
        self._cache_key = None

        # Cache for the multi-model bar plot components (top total + bottom decomposition)
        self._mm_bar_cache = None
        self._mm_bar_cache_key = None
        
    def _sync_selection(self, event):
        """Update master selection only if changed to avoid loops.

        This watcher comes from map Selection1D streams. event.new contains
        iloc indices relative to gdf_regions.
        """
        print(f"_sync_selection called (event.new={event.new})")
        self._is_syncing = True
        try:
            if self._selection_index != event.new:
                self._selection_index = event.new
                print(f"  master index -> {self._selection_index}")
                # propagate right away so other views update immediately
                try:
                    self._propagate_selection_to_streams(type('e',(object,),{'new':self._selection_index}))
                except Exception:
                    pass
        finally:
            self._is_syncing = False

    def _sync_selection_from_scatter(self, event):
        """Handle scatter stream selection by converting positions to region names.

        The scatter DataFrame is filtered (rows with NaN Type removed), so its
        indices do not match gdf_regions iloc positions. Convert them to
        region names, then forward to _sync_selection.
        """
        scatter_indices = event.new or []
        print(f"_sync_selection_from_scatter called (event.new={scatter_indices})")
        self._is_syncing = True
        try:
            if not scatter_indices:
                # No selection
                if self._selection_index != []:
                    self._selection_index = []
                    self._propagate_selection_to_streams(type('e',(object,),{'new':self._selection_index}))
            else:
                # Get the classified data (same as in get_scatter_plot)
                df_scatter = self._get_classified_data()
                df_scatter = df_scatter[df_scatter['Type'].notna()].copy()
                df_scatter = df_scatter.reset_index(drop=True)
                
                # Map scatter positions to region names
                try:
                    region_names = df_scatter['Region'].iloc[scatter_indices].tolist()
                    # Convert names to gdf_regions iloc indices
                    new_indices = [gdf_regions.index.get_loc(name) for name in region_names if name in gdf_regions.index]
                    
                    if self._selection_index != new_indices:
                        self._selection_index = new_indices
                        print(f"  scatter -> master index {self._selection_index}")
                        self._propagate_selection_to_streams(type('e',(object,),{'new':self._selection_index}))
                except Exception as e:
                    print(f"  scatter sync error: {e}")
        finally:
            self._is_syncing = False

    def _propagate_selection_to_streams(self, event):
        """Push the current indices into all registered map streams.

        Only propagate to maps (not scatter) to avoid re-triggering the
        scatter watcher. The scatter hook handles visual highlighting
        independently.
        """
        indices = event.new or []
        print(f"_propagate_selection_to_streams indices={indices}")
        
        for s in (self.v_map_s, self.t_map_s, self.sel_map_s):
            try:
                s.event(index=indices)
            except Exception:
                pass
    
    def _sync_from_sidebar(self, event):
        """Convert selected region names to indices when sidebar changes.

        After updating the master index we call the propagation helper so maps
        and the scatter are highlighted.
        """
        region_names = event.new
        print(f"_sync_from_sidebar event.new={region_names}")
        self._is_syncing = True
        try:
            if region_names:
                indices = [gdf_regions.index.get_loc(name) for name in region_names if name in gdf_regions.index]
                if self._selection_index != indices:
                    self._selection_index = indices
                    print(f"  sidebar -> master index {self._selection_index}")
                    self._propagate_selection_to_streams(type('e',(object,),{'new':self._selection_index}))
            else:
                if self._selection_index != []:
                    self._selection_index = []
                    self._propagate_selection_to_streams(type('e',(object,),{'new':self._selection_index}))
        finally:
            self._is_syncing = False
    
    def _sync_to_sidebar(self, event):
        """Convert selection indices to region names for sidebar display."""
        indices = event.new
        print(f"_sync_to_sidebar event.new={indices}")
        if indices:
            region_names = [gdf_regions.index[i] for i in indices if i < len(gdf_regions)]
            if self.selected_regions != region_names:
                self.selected_regions = region_names
        else:
            if self.selected_regions != []:
                self.selected_regions = []
            
    def _get_classified_data(self):
        """Helper to unify classification and color mapping for all regions - WITH CACHING."""
        # Convert list to tuple for hashing
        source_tuple = tuple(self.source) if self.source else ()
        cache_key = (self.model, self.season, self.term, self.nonlinear_pos, source_tuple, self.min_bias_threshold, self.slope_control)

        # Only recompute if cache key changes
        if self._cache_key == cache_key and self._cached_classified_data is not None:
            return self._cached_classified_data

        # Compute and cache
        result = compute_classified_data_v3(
            self.model, self.season, self.term, self.nonlinear_pos, 
            source_tuple, self.min_bias_threshold, self.slope_control
        )

        # Avoid repeated type conversions
        float_cols = ['X', 'Y', 'Conversion', 'Dynamical', 'Non_Linear', 'Net apparent']
        for col in float_cols:
            if col in result.columns and result[col].dtype != 'float':
                result[col] = result[col].astype('float')

        self._cached_classified_data = result
        self._cache_key = cache_key
        return result
    
    # Simple value map with simpler tooltips (no selection allowed)
    @param.depends('model', 'season', 'term', 'source', 'vmax', 'nonlinear_pos')
    def get_value_map_simple_tooltip(self):
        # use 'Net apparent' when all three bias components are included
        show_value=True
        label = 'Net apparent' if len(self.source) == 3 else ' + '.join(self.source)
        key = self.term.replace(" ", "_")
        value_line = f'<div style="margin-top: 5px;"><span style="font-size: 12px;"> @Source heavy precip. {self.term}: <b>@{{{key}}}{{0.0}}%</b></span></div>' if show_value else ""
        tooltips = f"""
        <div><span style="font-size: 13px; color: 'darkgrey'; font-weight: bold; ">@Region_Name</span></div>
        <div><span style="font-size: 10px; color: 'darkgrey'; font-weight: bold; ">{self.model}</span></div>
        {value_line} 
        """
        html_hover = HoverTool(tooltips=tooltips)
        
        # explicitly pass no selection stream so map is click‑free
        return self._render_map_base(
            self.term, 'BrBG', (-self.vmax, self.vmax),
            f"{self.model} | {self.season}\n{label} heavy precip. {self.term} (%)",
            None, self.map_r, extra_hooks=[self.hook_colorbar_only]
        )

    # include _selection_index so the value map redraws when selection changes
    @param.depends('_selection_index','model', 'season', 'term', 'source', 'vmax', 'nonlinear_pos')
    def get_value_map(self):
        # use 'Net apparent' when all three bias components are included
        label = 'Net apparent' if len(self.source) == 3 else ' + '.join(self.source)
        return self._render_map_base(self.term, 'BrBG', (-self.vmax, self.vmax), 
                                     f"{self.model} | {self.season}\n{label} heavy precip. {self.term} (%)", 
                                     self.v_map_s, self.map_r)

    # include _selection_index so classification map redraws when selection changes
    @param.depends('_selection_index','model', 'season', 'term', 'nonlinear_pos', 'min_bias_threshold', 'slope_control')
    def get_type_map(self):
        return self._render_map_base('Type', self.sector_cmap, 
                                     title=f"{self.model} | {self.season}\n{self.term.capitalize()} classification", 
                                     sel_stream=self.t_map_s, range_stream=self.map_r, 
                                     show_value=False)

    def _render_map_base(self, color_col, cmap, clim=None, title="", sel_stream=None, range_stream=None, show_value=True, extra_hooks=None):
        # Capture current selection before it gets potentially reset by new plot source
        current_index = self._selection_index
        
        # Capture current zoom/pan range
        current_x_range = range_stream.x_range
        current_y_range = range_stream.y_range
        
        # Defaults for PlateCarree (Europe/Med focus)
        default_xlim = (-11, 30)
        default_ylim = (30, 80)
        
        # Only override if the stream has valid, non-None ranges from a user interaction
        if current_x_range and all(x is not None for x in current_x_range):
            xlim = current_x_range
        else:
            xlim = default_xlim
            
        if current_y_range and all(y is not None for y in current_y_range):
            ylim = current_y_range
        else:
            ylim = default_ylim
        
        df_class = self._get_classified_data()
        gdf = gdf_regions.copy()
        # create a safe column name free of spaces for use in tooltips
        safe_term = self.term.replace(' ', '_')
        
        # Use more robust mapping to ensure region alignment
        if not df_class.empty:
            df_to_map = df_class.set_index('Region')
            gdf[self.term] = gdf.index.map(df_to_map['Selected_Sum'])
            # duplicate to safe column name so Bokeh can reference it without spaces
            gdf[safe_term] = gdf[self.term]
            gdf['Conversion'] = gdf.index.map(df_to_map['Conversion'])
            gdf['Dynamical'] = gdf.index.map(df_to_map['Dynamical'])
            gdf['Non_Linear'] = gdf.index.map(df_to_map['Non_Linear'])
            gdf['Net apparent'] = gdf.index.map(df_to_map['Net apparent'])
            gdf['Type'] = gdf.index.map(df_to_map['Type']).fillna('No Data')
            gdf['Text_Color'] = gdf.index.map(df_to_map['Text_Color']).fillna('#D3D3D3')
        else:
            # Fallback for empty data
            for col in [self.term, safe_term, 'Conversion', 'Dynamical', 'Non_Linear', 'Net apparent']:
                gdf[col] = 0
            gdf['Type'] = 'Minimal'
            gdf['Text_Color'] = 'grey'
        
        gdf.index = gdf.index.rename('Region_Name')
        gdf = gdf.reset_index()
        # label dataset for hover; use Net apparent when all three components
        gdf.loc[:,'Source'] = 'Net apparent' if len(self.source) == 3 else ' + '.join(self.source)

        # refer to safe_term (no spaces) in the tooltip field name
        value_line = f'<div style="margin-top: 5px;"><span style="font-size: 12px;">@Source {self.term}: <b>@{{{safe_term}}}{{0.0}}%</b></span></div>' if show_value else ""
        
        tooltips = f"""
        <div>
            <span style="font-size: 15px; color: @Text_Color; font-weight: bold;">@Region_Name</span>
        </div>
        <div><span style="font-size: 12px;">Type: <b>@Type {self.term}</b></span></div>
        {value_line} 
        <hr>
        <div><span style="font-size: 11px;">Conversion: @Conversion{{0.0}}%</span></div>
        <div><span style="font-size: 11px;">Dynamical: @Dynamical{{0.0}}%</span></div>
        <div><span style="font-size: 11px;">Non Linear: @Non_Linear{{0.0}}%</span></div>
        <hr>
        <div><span style="font-size: 11px;"><b>Net apparent {self.term}: @Net apparent{{0.0}}%</b></span></div>
        """
        html_hover = HoverTool(tooltips=tooltips)
        # configure tools/hooks depending on whether selection is enabled
        tools = [html_hover]
        hooks = []
        if sel_stream is not None:
            tools = ['tap', 'box_select', html_hover]
            hooks = [self.hook_selection]
        if extra_hooks:
            hooks = hooks + list(extra_hooks)
        
        plot_opts = dict(
            # frame_height=450, 
            # frame_width=500,
            responsive=True,
            aspect=0.85,
            tools=tools,
            cmap=cmap,
            color=color_col, 
            projection=ccrs.PlateCarree(),
            data_aspect=None,
            title=title,
            xlim=xlim, 
            ylim=ylim, 
            hooks=hooks, 
            line_color='black',
            line_width=0.4,
            selection_line_color='black',
            selection_line_width=0.4,
            active_tools=[],
            axiswise=True,
            nonselection_alpha=0.2
        )
        
        if clim is not None:
            plot_opts['clim'] = clim
            plot_opts['colorbar'] = True
        else:
            plot_opts['colorbar'] = False
            plot_opts['legend_position'] = 'top_left'

        # Back to PlateCarree with data_aspect=1 for correct aspect without coordinate issues
        poly_plot = gdf.hvplot.polygons(
            crs=ccrs.PlateCarree(),
            color=color_col,
            hover_cols=['Region_Name', 'Source', 'Conversion', 'Dynamical', 'Non_Linear', 'Net apparent', 'Type', 'Text_Color'],
            geo=True
        ).opts(**plot_opts)
                 
        # IMPORTANT: attach the persistent streams to the new plot
        if sel_stream is not None:
            sel_stream.source = poly_plot
        if range_stream is not None:
            range_stream.source = poly_plot
        
        # Selection and ranges are now primarily handled by opts/hooks and dependencies
        return poly_plot
        
    def hook_selection(self, plot, element):
        if not plot.state:
            return
            
        # 0. Sync Bokeh ranges for linked axes across tabs
        if self._shared_x_range is None:
            self._shared_x_range = plot.state.x_range
            self._shared_y_range = plot.state.y_range
        else:
            plot.state.x_range = self._shared_x_range
            plot.state.y_range = self._shared_y_range

        # 1. Manually set the selection indices on the plot's data source if available
        if 'source' in plot.handles:
             plot.handles['source'].selected.indices = self._selection_index or []
        
        # 2. Style legend if this is a qualitative map (Type map)
        if plot.state.legend:
            legend = plot.state.legend[0] if isinstance(plot.state.legend, list) else plot.state.legend
            try:
                legend.background_fill_alpha = 0.5
                legend.border_line_color = 'grey'
                legend.orientation = 'horizontal'
                legend.ncols = 2 # 5 items in 2 columns = 3 lines
            except Exception:
                pass

        # Handle ColorBar (Values map)
        # Check all layout sides where HoloViews/Bokeh might put it
        for side in ['right', 'left', 'above', 'below', 'center']:
            side_layout = getattr(plot.state, side)
            cbars = [r for r in side_layout if 'ColorBar' in str(type(r))]
            for cbar in cbars:
                try:
                    # If it's not in center yet, move it
                    if side != 'center':
                        side_layout.remove(cbar)
                        plot.state.add_layout(cbar, 'center')
                    
                    cbar.location = 'top_left'
                    cbar.orientation = 'horizontal'
                    # Sizes
                    cbar.height = 12
                    cbar.width = 250      # Proportional to plot width
                    # Font sizes & labels
                    cbar.title_text_font_size = '9pt'
                    cbar.label_text_font_size = '8pt'
                    cbar.major_tick_out = 3
                    cbar.label_standoff = 3
                    # Visibility & Style
                    cbar.background_fill_color = 'white'
                    cbar.background_fill_alpha = 0.8
                    cbar.border_line_color = 'grey'
                    cbar.level = 'overlay' # Ensure it is on top
                except Exception:
                    pass


    @param.depends('_selection_index', 'model', 'season', 'term', 'min_bias_threshold', 'slope_control', 'vmax', 'nonlinear_pos')
    def get_secondary_plot(self, **kwargs):
        if not self._selection_index:
            return "### Please select a region"
        
        region_iloc_idxs = self._selection_index
        regions = gdf_regions.iloc[region_iloc_idxs].index.tolist()
        
        # Select data for all sources because bars typically show decomposition
        ds_sel_barplot = data_ensemble_mean.sel(model=self.model, season=self.season, term=self.term, region_id=regions)
            
        # Convert to tidy DataFrame for easier plotting with tooltips
        df = ds_sel_barplot.to_dataframe(name=self.term).reset_index()
        # Ensure column names match tooltip expectations
        # ds_sel_barplot has dims (region_id, source)
        # to_dataframe -> index (region_id, source), value (self.term)
        # reset_index -> region_id, source, self.term
        # Rename if necessary based on existing coords
        # If coords are named 'region_id' and 'source', we map them for clarity
        df = df.rename(columns={'region_id': 'Region', 'source': 'Source'})
        df['Region_Display'] = df['Region']

        tooltips = f"""
        <div>
            <span style="font-size: 15px; color: blue; font-weight: bold;">@Region_Display</span>
        </div>
        <div>
            <span style="font-size: 12px;">@Source {self.term}</span>
        </div>
        <div>
            <span style="font-size: 12px;">@{self.term}</span>
        </div>
        """
        hover = HoverTool(tooltips=tooltips)
        
        # Plot with detailed tooltips
        # Stacked? Or Side-by-side?
        # Typically one region -> one set of bars (Source vs Term).
        # Multiple regions -> Grouped? Or just stacked?
        # Let's keep it simple: x=Term, y=Source (horizontal bars)
        
        bars = df.hvplot.barh(
            x='Source', 
            y=self.term, 
            by='Region',
            title=f"{self.term} by Source",
            tools=[hover],
            hover_cols=['Region_Display']
        )
        bars_out = bars.opts(height=400, width=400, toolbar='above') * hv.HLine(0).opts(color='k')
        return bars_out
        
    # OPTIMIZATION 4: Cache background generation
    @lru_cache(maxsize=32)
    def _get_scatter_background_cached(self, slope, min_bias, vmax, diag, show_diag_lines, show_diamonds):
        """Cached background generation.

        `diag` controls the spacing (in percent) between diagonal dashed
        constant-apparent-bias lines.
        """
        L = 200
        S = slope
        M = min_bias
        
        bg_poly_data = [
            {'x': [0, -S*L, -L, -L, 0], 'y': [0, L, L, S*L, 0], 'type': 'Compensating'},
            {'x': [0, S*L, L, L, 0], 'y': [0, -L, -L, -S*L, 0], 'type': 'Compensating'},
            {'x': [0, S*L, L, L, 0], 'y': [0, L, L, S*L, 0], 'type': 'Compounding'},
            {'x': [0, -S*L, -L, -L, 0], 'y': [0, -L, -L, -S*L, 0], 'type': 'Compounding'},
            {'x': [0, S*L, -S*L, 0], 'y': [0, L, L, 0], 'type': 'Dynamical'},
            {'x': [0, -S*L, S*L, 0], 'y': [0, -L, -L, 0], 'type': 'Dynamical'},
            {'x': [0, L, L, 0], 'y': [0, S*L, -S*L, 0], 'type': 'Conversion'},
            {'x': [0, -L, -L, 0], 'y': [0, -S*L, S*L, 0], 'type': 'Conversion'}
        ]
        
        min_poly_data = [{'x': [M, 0, -M, 0, M], 'y': [0, M, 0, -M, 0], 'type': 'Minimal'}]
        
        bg_polys = hv.Polygons(bg_poly_data, vdims='type').opts(
            color='type', cmap=self.sector_cmap, alpha=0.5, line_width=0.5,line_color='grey', apply_ranges=False, tools=[]
        )
        
        min_poly = hv.Polygons(min_poly_data, vdims='type').opts(
            color='type', cmap=self.sector_cmap, alpha=1, line_width=0.5, line_color='grey', apply_ranges=False, tools=[]
        )
        
        # Add labels - use term from instance (not cacheable, so we'll add them outside)
        lines = []

        # Constant apparent bias lines (y = -x + k)
        if show_diag_lines:
            for k in range(0, 200, diag):
                if k == 0: continue
                xs = np.array([-L, L])
                ys = -xs + k
                lines.append(hv.Curve((xs, ys)).opts(color='grey', line_width=0.5, line_dash='dashed', alpha=0.5))
            for k in range(0, -200, -diag):
                if k == 0: continue
                xs = np.array([-L, L])
                ys = -xs + k
                lines.append(hv.Curve((xs, ys)).opts(color='grey', line_width=0.5, line_dash='dashed', alpha=0.5))

        xs = np.array([-L, L])
        ys = -xs
        lines.append(hv.Curve((xs, ys)).opts(color='black', line_width=1.0, line_dash='dashed', alpha=0.6))

        # Diamonds of constant total bias: |x| + |y| = c
        if show_diamonds:
            for c in range(diag, int(L * 1.5), diag):
                diamond_xs = [c, 0, -c, 0, c]
                diamond_ys = [0, c, 0, -c, 0]
                lines.append(hv.Curve((diamond_xs, diamond_ys)).opts(
                    color='grey', line_width=0.5, line_dash='dashed', alpha=0.5, apply_ranges=False
                ))
            
        return bg_polys * min_poly * hv.Overlay(lines).opts(apply_ranges=False)
    
    def get_scatter_background(self, x_range=(-150, 150), y_range=(-150, 150)):
        """Generates the background sectors based on current slope and minimal bias settings."""
        # Get cached background (include diagonal interval setting)
        bg = self._get_scatter_background_cached(self.slope_control, self.min_bias_threshold, self.vmax, self.diag_interval, self.show_diag_lines, self.show_diamonds)
        
        # Add labels (not cached because they depend on self.term)
        labels = [
            hv.Text(0, 0, f"Minimal {self.term.split(' ')[0]}", fontsize=8),
            hv.Text(90, 0, 'Conversion', fontsize=9),
            hv.Text(-90, 0, 'Conversion', fontsize=9),
            hv.Text(0, 90, 'Dynamical', fontsize=9, rotation=90),
            hv.Text(0, -90, 'Dynamical', fontsize=9, rotation=90),
            hv.Text(70, 70, 'Compounding', fontsize=9),
            hv.Text(-70, -70, 'Compounding', fontsize=9),
            hv.Text(-70, 70, 'Compensating', fontsize=9),
            hv.Text(70, -70, 'Compensating', fontsize=9),
        ]
        # <div><span style="font-size: 15px; color: @Text_Color; font-weight: bold;">@Region</span>
        # </div>
        
        tooltip_info = {
            "bias":[ f"<div><span style='font-size: 11px; font-weight: bold;'>Minimal bias:</span></div><div>{tooltips_strings.Minimal_Bias}</div>", 
                     f"<div><span style='font-size: 11px; font-weight: bold;'>Conversion bias:</span></div><div>{tooltips_strings.Conversion_Bias_right}</div>", 
                     f"<div><span style='font-size: 11px; font-weight: bold;'>Conversion bias:</span></div><div>{tooltips_strings.Conversion_Bias_left}</div>", 
                     f"<div><span style='font-size: 11px; font-weight: bold;'>Dynamical bias:</span></div><div>{tooltips_strings.Dynamical_Bias_top}</div>", 
                     f"<div><span style='font-size: 11px; font-weight: bold;'>Dynamical bias:</span></div><div>{tooltips_strings.Dynamical_Bias_bottom}</div>", 
                     f"<div><span style='font-size: 11px; font-weight: bold;'>Compounding bias:</span></div><div>{tooltips_strings.Compounding_Bias_upper}</div>", 
                     f"<div><span style='font-size: 11px; font-weight: bold;'>Compounding bias:</span></div><div>{tooltips_strings.Compounding_Bias_lower}</div>", 
                     f"<div><span style='font-size: 11px; font-weight: bold;'>Compensating bias:</span></div><div>{tooltips_strings.Compensating_Bias_upper}.</div>",
                     f"<div><span style='font-size: 11px; font-weight: bold;'>Compensating bias:</span></div><div>{tooltips_strings.Compensating_Bias_lower}</div>"],
            "change":
                    [f"<div><span style='font-size: 11px; font-weight: bold;'>Minimal Trend:</span></div><div>{tooltips_strings.Minimal_Trend}</div>",
                     f"<div><span style='font-size: 11px; font-weight: bold;'>Conversion Trend:</span></div><div>{tooltips_strings.Conversion_Trend_right}</div>",
                     f"<div><span style='font-size: 11px; font-weight: bold;'>Conversion Trend:</span></div><div>{tooltips_strings.Conversion_Trend_left}</div>",
                     f"<div><span style='font-size: 11px; font-weight: bold;'>Dynamical Trend:</span></div><div>{tooltips_strings.Dynamical_Trend_top}</div>",
                     f"<div><span style='font-size: 11px; font-weight: bold;'>Dynamical Trend:</span></div><div>{tooltips_strings.Dynamical_Trend_bottom}</div>",
                     f"<div><span style='font-size: 11px; font-weight: bold;'>Compounding Trend:</span></div><div>{tooltips_strings.Compounding_Trend_upper}</div>",
                     f"<div><span style='font-size: 11px; font-weight: bold;'>Compounding Trend:</span></div><div>{tooltips_strings.Compounding_Trend_lower}</div>",
                     f"<div><span style='font-size: 11px; font-weight: bold;'>Compensating Trend:</span></div><div>{tooltips_strings.Compensating_Trend_upper}</div>",
                     f"<div><span style='font-size: 11px; font-weight: bold;'>Compensating Trend:</span></div><div>{tooltips_strings.Compensating_Trend_lower}</div>"],
            "uncalibrated_change": 
                    [f"<div><span style='font-size: 11px; font-weight: bold;'>Minimal Trend:</span></div><div>{tooltips_strings.Minimal_Trend}</div>",
                     f"<div><span style='font-size: 11px; font-weight: bold;'>Conversion Trend:</span></div><div>{tooltips_strings.Conversion_Trend_right}</div>",
                     f"<div><span style='font-size: 11px; font-weight: bold;'>Conversion Trend:</span></div><div>{tooltips_strings.Conversion_Trend_left}</div>",
                     f"<div><span style='font-size: 11px; font-weight: bold;'>Dynamical Trend:</span></div><div>{tooltips_strings.Dynamical_Trend_top}</div>",
                     f"<div><span style='font-size: 11px; font-weight: bold;'>Dynamical Trend:</span></div><div>{tooltips_strings.Dynamical_Trend_bottom}</div>",
                     f"<div><span style='font-size: 11px; font-weight: bold;'>Compounding Trend:</span></div><div>{tooltips_strings.Compounding_Trend_upper}</div>",
                     f"<div><span style='font-size: 11px; font-weight: bold;'>Compounding Trend:</span></div><div>{tooltips_strings.Compounding_Trend_lower}</div>",
                     f"<div><span style='font-size: 11px; font-weight: bold;'>Compensating Trend:</span></div><div>{tooltips_strings.Compensating_Trend_upper}</div>",
                     f"<div><span style='font-size: 11px; font-weight: bold;'>Compensating Trend:</span></div><div>{tooltips_strings.Compensating_Trend_lower}</div>"],}

        data = dict(
                x=[0.,90,-90,0,0,70,-70,-70,70],
                y=[0.,0,0,90,-90,70,-70,70,-70],
                label=["Minimal", "Conversion", "Conversion", "Dynamical", "Dynamical", "Compounding", "Compounding", "Compensating", "Compensating"],
                description=["Minimal bias","Conversion bias (model produces too much heavy precip.)","Conversion bias (model produces too little heavy precip.)","Dynamical bias (precursor patterns too frequent)","Dynamical bias (precursor patterns too rare)","Compounding bias (precursor patterns too frequent and too likely to produce heavy precip.)","Compounding bias (precursor patterns too rare and too unlikely to produce heavy precip.)","Compensating bias (precursor patterns too frequent but less likely to produce heavy precip.)","Compensating bias (precursor patterns too rare but more likely to produce heavy precip.)"],
                rotation=[0,0,0,90,90,0,0,0,0],
                fontsize=9,
                info=tooltip_info[self.term]
            )
        points = hv.Points(data, kdims=["x", "y"], vdims=["label", "description","rotation", "fontsize", "info"])

        text = hv.Labels(points, kdims=["x", "y"], vdims=["label"])
        hover = HoverTool(tooltips="""
                                    <div style="width: 200px; white-space: normal; font-size: 11px;">
                                        @info{safe}
                                    </div>
                                   """)
        # hover = HoverTool(tooltips=[
        #     ("Description", "@description")
        #     ])
        labels = points.opts(size=10, tools=[hover], alpha=0)*text.opts(text_color='black', text_font_size='8pt', text_align='center', text_baseline='middle', apply_ranges=False)
        return bg * labels

    # scatter must depend on _selection_index so it re-renders when selection changes
    # and the hook can apply highlighting to the plot
    @param.depends('_selection_index','model', 'season', 'term', 'nonlinear_pos', 'min_bias_threshold', 'slope_control', 'vmax', 'diag_interval', 'show_diag_lines', 'show_diamonds', watch=True)
    def get_scatter_plot(self):
        # Get standardized classified data (cached)
        df_scatter = self._get_classified_data()
        
        # Filter out rows with NaN Type (missing data)
        df_scatter = df_scatter[df_scatter['Type'].notna()].copy()
        
        # Setup labels based on nonlinear position
        if self.nonlinear_pos == 'Dynamical':
            x_label = f"Conversion {self.term} (%)"
            y_label = f"Dynamical + Non Linear {self.term} (%)"
        else:
            x_label = f"Conversion + Non Linear {self.term} (%)"
            y_label = f"Dynamical {self.term} (%)"
        
        # Shared Color map for sectors
        cmap = self.sector_cmap
        
        if 'Net apparent' not in df_scatter.columns:
            df_scatter['Net apparent'] = df_scatter['Conversion'] + df_scatter['Dynamical'] + df_scatter['Non_Linear']
        
        tooltips = f"""
        <div>
            <span style="font-size: 15px; color: @Text_Color; font-weight: bold;">@Region</span>
        </div>
        <div><span style="font-size: 12px;">Type: <b>@Type {self.term}</b></span></div>
        <div style="margin-top: 5px;"><span style="font-size: 11px;">{x_label.replace(' (%)','')}: <b>@X{{0.0}}%</b></span></div>
        <div><span style="font-size: 11px;">{y_label.replace(' (%)','')}: <b>@Y{{0.0}}%</b></span></div>
        <hr>
        <div><span style="font-size: 11px;">Conversion: @Conversion{{0.0}}%</span></div>
        <div><span style="font-size: 11px;">Dynamical: @Dynamical{{0.0}}%</span></div>
        <div><span style="font-size: 11px;">Non Linear: @Non_Linear{{0.0}}%</span></div>
        <hr>
        <div><span style="font-size: 11px;"><b>Net apparent {self.term}: @Net apparent{{0.0}}%</b></span></div>
        """
        hover = HoverTool(tooltips=tooltips)
        
        opts = dict(
            title=f"{self.model} | {self.season}\n{self.term.capitalize()} classification",
            xlabel=x_label,
            ylabel=y_label,
            responsive=True,
            aspect=0.85,
            hooks=[self.hook_scatter_selection],
            xlim=(-self.vmax, self.vmax),
            ylim=(-self.vmax, self.vmax),
            nonselection_alpha=0.3,
            selection_line_color="black",
            selection_line_width=2,
        )
            
        scatter = df_scatter.hvplot.scatter(
            x='X', 
            y='Y', 
            hover_cols=['Region', 'X', 'Y', 'Conversion', 'Dynamical', 'Non_Linear', 'Net apparent', 'Type', 'Text_Color'],
            tools=['pan', 'wheel_zoom', 'tap', 'box_select', hover],
            color='Type',
            cmap=cmap,
            size=60,
            line_color='black',
            line_width=0.6,
            legend=False,
            aspect='equal'
        ).opts(**opts)
        
        background = self.get_scatter_background()
        plot = (background * scatter).opts(active_tools=['pan'])
        
        # attach stream to the scatter element so selection events fire correctly
        self.scat_s.source = scatter
             
        return plot

    def hook_scatter_selection(self, plot, element):
        # The scatter plot may be built from a filtered DataFrame so the
        # row positions (selected.indices) do *not* always match the
        # master region index.  We therefore translate back and forth using
        # the region name stored in the data source.
        if 'source' not in plot.handles:
            return

        df = pd.DataFrame(plot.handles['source'].data)

        # Apply master selection to scatter (visual highlighting)
        # Master selection contains gdf_regions iloc indices; convert to region names
        if self._selection_index:
            master_names = [gdf_regions.index[i] for i in self._selection_index
                            if i < len(gdf_regions)]
            scatter_pos = df.index[df['Region'].isin(master_names)].tolist()
        else:
            scatter_pos = []
        plot.handles['source'].selected.indices = scatter_pos
        print(f"hook_scatter_selection set scatter_pos {scatter_pos} from master {self._selection_index}")

    def hook_multi_model_legend(self, plot, element):
        if not plot.state or not plot.state.legend:
            return

        legend = plot.state.legend[0] if isinstance(plot.state.legend, list) else plot.state.legend
        merged_items = []
        grouped_items = {}
        mean_renderers = []

        for item in legend.items:
            label = item.label
            if isinstance(label, dict):
                label_value = label.get('value')
            else:
                label_value = getattr(label, 'value', label)

            if label_value is None:
                merged_items.append(item)
                continue

            if label_value not in grouped_items:
                merged_item = LegendItem(label=item.label, renderers=list(item.renderers))
                grouped_items[label_value] = merged_item
                merged_items.append(merged_item)
                continue

            for renderer in item.renderers:
                data = getattr(getattr(renderer, 'data_source', None), 'data', {})
                if 'Net apparent' in data and 'Type' in data and renderer not in mean_renderers:
                    mean_renderers.append(renderer)
                if renderer not in grouped_items[label_value].renderers:
                    grouped_items[label_value].renderers.append(renderer)

        for item in merged_items:
            for renderer in item.renderers:
                data = getattr(getattr(renderer, 'data_source', None), 'data', {})
                if 'Net apparent' in data and 'Type' in data and renderer not in mean_renderers:
                    mean_renderers.append(renderer)

        legend.items = merged_items
        legend.click_policy = 'mute'

        for tool in plot.state.tools:
            if isinstance(tool, HoverTool):
                tool.renderers = mean_renderers

    # OPTIMIZATION 6: Most important - make bar plot only depend on selection, use cached data
    @param.depends('_selection_index', 'bar_sort', 'bar_sort_ascending')
    def get_bar_plot(self):
        if not self._selection_index:
            return #pn.pane.Markdown(f"### {self.term.capitalize()} Decomposition: No region selected\n*Click on a map or scatter point to see the breakdown*")
        
        # OPTIMIZATION: Get cached data, then filter - don't recompute!
        df_class = self._get_classified_data()
        selected_data = df_class.iloc[self._selection_index].copy()
        
        # Melt to get components for grouping
        melted = selected_data.melt(
            id_vars=['Region', 'Type', 'Text_Color'], 
            value_vars=['Conversion', 'Dynamical', 'Non_Linear'],
            var_name='Component', 
            value_name='Value'
        )
        
        # Calculate Net apparent for each region and append to melted
        totals = selected_data.copy()
        totals['Component'] = 'Net apparent'
        totals['Value'] = totals['Conversion'] + totals['Dynamical'] + totals['Non_Linear']
        totals = totals[['Region', 'Type', 'Text_Color', 'Component', 'Value']]
        
        melted = pd.concat([melted, totals], ignore_index=True)
        
        # Ensure bar order: Net apparent first, then Dynamical, Conversion and Non_Linear
        order = ['Non_Linear', 'Conversion', 'Dynamical', 'Net apparent']
        melted['Component'] = pd.Categorical(melted['Component'], categories=order, ordered=True)
        # sorting ensures categories appear in the specified order in the plot
        melted = melted.sort_values('Component', key=lambda col: col.cat.codes)

        # Sort regions by the selected sort key (ascending so largest bar is at top with invert_axes)
        sort_col = self.bar_sort  # e.g. 'Net apparent', 'Conversion', 'Dynamical', 'Non_Linear'
        sort_vals = melted[melted['Component'] == sort_col].set_index('Region')['Value']
        region_order = sort_vals.sort_values(ascending=self.bar_sort_ascending).index.tolist()
        melted['Region'] = pd.Categorical(melted['Region'], categories=region_order, ordered=True)
        melted = melted.sort_values(['Region', 'Component'])
        
        # Create Tooltip
        tooltips = f"""
        <div>
            <span style="font-size: 14px; font-weight: bold;">@Region</span>
        </div>
        <div>
            <span style="font-size: 12px; color: #333;">@Component {self.term}: <b>@Value{{0.0}}%</b></span>
        </div>
        """
        hover = HoverTool(tooltips=tooltips)

        # Define colors including Net apparent
        bar_cmap = {
            'Conversion': '#FDFD96',
            'Dynamical': '#ADD8E6',
            'Non_Linear': '#81C784',
            'Net apparent': '#EEEEEE'
        }

        melted_comp  = melted[melted['Component'] != 'Net apparent']
        melted_total = melted[melted['Component'] == 'Net apparent']

        common_opts = dict(
            show_legend=False,
            default_tools=[],
            tools=[hover, 'xwheel_zoom', 'xpan', 'save', 'reset'],
            active_tools=['xwheel_zoom', 'xpan'],
            toolbar='above',
            invert_axes=True,
            color='Component',
            cmap=bar_cmap,
            xlim=(-self.vmax, self.vmax),
        )

        from bokeh.models import Range1d
        shared_x = Range1d(start=-self.vmax, end=self.vmax)
        def _sync_x(plot, element):
            plot.state.x_range = shared_x

        bar_comp = hv.Bars(melted_comp, kdims=['Component', 'Region'], vdims='Value').opts(
            title=f"{self.term.capitalize()} Decomposition ({self.season})",
            xlabel="", ylabel=f"{self.term.capitalize()} (%)",
            frame_height=340,
            hooks=[_sync_x],
            **common_opts
        )
        melted_total = melted_total.copy()
        melted_total['Component'] = melted_total['Component'].cat.remove_unused_categories()
        bar_total = hv.Bars(melted_total, kdims=['Component', 'Region'], vdims='Value').opts(
            title=f"Net Apparent {self.term.capitalize()} ({self.season})",
            xlabel="", ylabel="",
            frame_height=100,
            hooks=[_sync_x],
            **common_opts
        )

        vmax_pos  = hv.HLine( self.vmax).opts(color='red',   line_dash='dashed', line_width=1.5, alpha=0.6)
        vmax_neg  = hv.HLine(-self.vmax).opts(color='red',   line_dash='dashed', line_width=1.5, alpha=0.6)
        zero_line = hv.HLine(0).opts(color='black', line_width=1.0, alpha=0.8)

        return pn.Column(
            pn.panel(bar_total * zero_line * vmax_pos * vmax_neg, sizing_mode='stretch_width', linked_axes=False),
            pn.panel(bar_comp  * zero_line * vmax_pos * vmax_neg, sizing_mode='stretch_width', linked_axes=False),
            sizing_mode='stretch_width', max_width=2000, margin=(20, 0, 0, 20)
        )

    @param.depends('_selection_index', 'season', 'term', 'selected_models', 'nonlinear_pos', 'min_bias_threshold', 'slope_control')
    def get_classification_pie_chart(self):
        """Small Bokeh pie chart showing classification counts across selected models for the current region."""
        import math

        type_colors = {
            'Minimal':     '#7af9ab',
            'Conversion':  '#e2ca76',
            'Dynamical':   '#b1d1fc',
            'Compounding': '#c5b5d4',
            'Compensating':  '#de7f8b',
            'No Data':     '#D3D3D3',
        }

        if not self._selection_index:
            types = ['No Data']
            counts = [1]
        else:
            region_name = gdf_regions.iloc[self._selection_index[0]].name
            source_tuple = tuple(self.source) if self.source else ()
            type_list = []
            for model in self.selected_models:
                df_m = compute_classified_data_v3(
                    model, self.season, self.term, self.nonlinear_pos,
                    source_tuple, self.min_bias_threshold, self.slope_control
                )
                if df_m.empty:
                    type_list.append('No Data')
                else:
                    row = df_m[df_m['Region'] == region_name]
                    type_list.append(row['Type'].values[0] if not row.empty else 'No Data')

            from collections import Counter
            counts_dict = Counter(type_list)
            types = list(counts_dict.keys())
            counts = list(counts_dict.values())

        total = sum(counts)
        angles = [c / total * 2 * math.pi for c in counts]
        colors = [type_colors.get(t, '#CCCCCC') for t in types]

        p = bokeh_figure(
            toolbar_location=None,
            x_range=(-1.25, 2.9),
            y_range=(-1.1, 1.1),
            background_fill_alpha=0.0,
            border_fill_alpha=0.0,
            background_fill_color=None,
            border_fill_color=None,
            outline_line_color=None,
            sizing_mode='stretch_both',
            min_width=160,
            min_height=120,
        )
        p.axis.visible = False
        p.grid.visible = False

        # Draw wedges
        start = -math.pi / 2
        for i, (t, c, a, col) in enumerate(zip(types, counts, angles, colors)):
            end = start + a
            p.wedge(
                x=0, y=0, radius=0.5,
                start_angle=start, end_angle=end,
                line_color='white', line_width=0.8,
                fill_color=col,
                legend_label=f"{t}: {c}"
            )
            start = end

        p.legend.location = 'top_right'
        p.legend.label_text_font_size = '7pt'
        p.legend.spacing = 1
        p.legend.padding = 3
        p.legend.margin = 2
        p.legend.glyph_width = 10
        p.legend.glyph_height = 10
        p.legend.background_fill_alpha = 0.7
        p.legend.border_line_color = 'grey'

        return pn.pane.Bokeh(p, margin=0)

    @param.depends('_selection_index')
    def get_selector_map(self):
        # Simplified map for region selection
        gdf = gdf_regions.reset_index().rename(columns={'index': 'Region_Name'})
        gdf['Color'] = '#E0E0E0' # Lighter grey
        
        tooltips = "<div><span style='font-size: 14px; font-weight: bold;'>@Region_Name</span></div>"
        html_hover = HoverTool(tooltips=tooltips)
        
        # if no region is selected yet, default to index 12
        if not self._selection_index:
            self._selection_index = [11]
            # propagate this initial choice to the other streams so plots update
            self._propagate_selection_to_streams(type('e',(object,),{'new':self._selection_index}))

        plot = gdf.hvplot.polygons(
            crs=ccrs.PlateCarree(),
            color='Color',
            geo=True,
            hover_cols=['Region_Name']
        ).opts(
            default_tools=[],
            responsive=True,
            tools=['tap', 'box_select', html_hover],
            active_tools=[],
            selection_color='red',
            nonselection_color='#E0E0E0',
            nonselection_alpha=1.0,
            line_color='black',
            line_width=0.4,
            selection_line_color='black',
            selection_line_width=0.4,
            nonselection_line_color='black',
            nonselection_line_width=0.4,
            projection=ccrs.PlateCarree(),
            xlim=(-11, 30),
            ylim=(30, 80),
            hooks=[self.hook_selection],
            axiswise=True,
            title=f"Click on a region\nfor multimodel {self.term} analysis.\nCurrent: {self.selected_regions[0]} | {self.season}",
            toolbar=None
        )
        
        self.sel_map_s.source = plot
        return plot

    def _compute_multi_model_bars(self):
        """Compute (and cache) the two Bars elements used by the multi-model
        bar plot: the top 'total' plot and the bottom 'decomposition' plot.

        Cached on the same param dependencies as the public getters below so
        we only build the dataframe/plots once per parameter change instead
        of twice (once per getter).
        """
        cache_key = (
            tuple(self._selection_index), self.season, self.term,
            tuple(self.selected_models), self.show_ensemble_members,
            self.nonlinear_pos, self.min_bias_threshold, self.slope_control,
            self.vmax, self.bar_sort, self.bar_sort_ascending
        )
        if self._mm_bar_cache_key == cache_key and self._mm_bar_cache is not None:
            return self._mm_bar_cache

        if not self._selection_index:
            self._mm_bar_cache = (None, None)
            self._mm_bar_cache_key = cache_key
            return self._mm_bar_cache

        region_names = gdf_regions.iloc[self._selection_index].index.tolist()
        region_name = region_names[0]  # For simplicity, just take the first selected region for the multi-model comparison
        # Define colors consistent with get_bar_plot
        bar_cmap = {
            'Conversion': '#FDFD96',
            'Dynamical': '#ADD8E6',
            'Non Linear': '#81C784',
            'Net apparent': '#EEEEEE'
        }
        ds_region = data_ensemble_mean.sel(model=self.selected_models, season=self.season, term=self.term, region_id=region_name)

        # Convert to tidy DataFrame
        df = ds_region.to_dataframe(name='Value').reset_index()
        df = df.rename(columns={'source': 'Component'})

        # Calculate Net apparent for each model
        totals = df.groupby('model')['Value'].sum(min_count=1).reset_index()
        totals['Component'] = 'Net apparent'

        df = pd.concat([df, totals], ignore_index=True)
        # Ensure bar order: Net apparent first, then Dynamical, Conversion and Non_Linear
        order = ['Non Linear', 'Conversion', 'Dynamical', 'Net apparent']
        df['Component'] = pd.Categorical(df['Component'], categories=order, ordered=True)
        # sorting ensures categories appear in the specified order in the plot
        df = df.sort_values('Component', key=lambda col: col.cat.codes)

        # Sort models by the selected sort key
        sort_col = self.bar_sort.replace('_', ' ')  # 'Non_Linear' -> 'Non Linear'
        sort_vals = df[df['Component'] == sort_col].set_index('model')['Value']
        model_order = sort_vals.sort_values(ascending=self.bar_sort_ascending).index.tolist()
        df['model'] = pd.Categorical(df['model'], categories=model_order, ordered=True)
        df = df.sort_values(['model', 'Component'])

        # Create Tooltip
        tooltips = f"""
        <div>
            <span style="font-size: 14px; font-weight: bold;">@model</span>
        </div>
        <div>
            <span style="font-size: 12px; color: #333;">@Component {self.term}: <b>@Value{{0.0}}%</b></span>
        </div>
        """
        hover = HoverTool(tooltips=tooltips)

        df_comp  = df[df['Component'] != 'Net apparent']
        df_total = df[df['Component'] == 'Net apparent']

        # NOTE: responsive=True (rather than a fixed frame_height) so each
        # plot fills whatever grid cell it is placed into and rescales
        # smoothly when the browser window is resized.
        common_opts = dict(
            invert_axes=True,
            show_legend=False,
            default_tools=[],
            tools=[hover, 'xwheel_zoom', 'xpan', 'save', 'reset'],
            active_tools=['xwheel_zoom', 'xpan'],
            toolbar='above',
            color='Component',
            cmap=bar_cmap,
            selection_color='red',
            nonselection_alpha=0.4,
            xlim=(-self.vmax, self.vmax),
            responsive=True,
        )

        from bokeh.models import Range1d
        shared_x = Range1d(start=-self.vmax, end=self.vmax)
        def _sync_x(plot, element):
            plot.state.x_range = shared_x

        bar_comp = hv.Bars(df_comp, kdims=['Component', 'model'], vdims='Value').opts(
            title=f"{self.term.capitalize()} Decomposition ({self.season})",
            xlabel="", ylabel=f"{self.term.capitalize()} (%)",
            hooks=[_sync_x],
            **common_opts
        )
        df_total = df_total.copy()
        df_total['Component'] = df_total['Component'].cat.remove_unused_categories()
        bar_total = hv.Bars(df_total, kdims=['Component', 'model'], vdims='Value').opts(
            title=f"Net Apparent {self.term.capitalize()} ({self.season})",
            xlabel="", ylabel="",
            hooks=[_sync_x],
            **common_opts
        )

        zero_line = hv.HLine(0).opts(color='black', line_width=1.0, alpha=0.8)

        self._mm_bar_cache = (bar_total * zero_line, bar_comp * zero_line)
        self._mm_bar_cache_key = cache_key
        return self._mm_bar_cache

    @param.depends('_selection_index', 'season', 'term', 'selected_models', 'show_ensemble_members', 'nonlinear_pos', 'min_bias_threshold', 'slope_control', 'vmax', 'bar_sort', 'bar_sort_ascending')
    def get_multi_model_bar_total(self):
        """Top 'b' cell: net-apparent totals per model."""
        bar_total, _ = self._compute_multi_model_bars()
        if bar_total is None:
            return None
        return pn.panel(bar_total, sizing_mode='stretch_both', linked_axes=False)

    @param.depends('_selection_index', 'season', 'term', 'selected_models', 'show_ensemble_members', 'nonlinear_pos', 'min_bias_threshold', 'slope_control', 'vmax', 'bar_sort', 'bar_sort_ascending')
    def get_multi_model_bar_decomp(self):
        """Bottom 'B' cell: per-source decomposition per model."""
        _, bar_comp = self._compute_multi_model_bars()
        if bar_comp is None:
            return None
        return pn.panel(bar_comp, sizing_mode='stretch_both', linked_axes=False)

    @param.depends('_selection_index', 'season', 'term', 'selected_models', 'show_ensemble_members', 'nonlinear_pos', 'min_bias_threshold', 'slope_control', 'vmax', 'bar_sort', 'bar_sort_ascending')
    def get_multi_model_bar_plot(self):
        """Kept for backwards compatibility (e.g. if used elsewhere): stacks
        the total and decomposition plots vertically in one column."""
        bar_total, bar_comp = self._compute_multi_model_bars()
        if bar_total is None:
            return None
        return pn.Column(
            pn.panel(bar_total, sizing_mode='stretch_width', linked_axes=False, height=140),
            pn.panel(bar_comp, sizing_mode='stretch_width', linked_axes=False, height=340),
            sizing_mode='stretch_width', margin=0
        )

    @param.depends('_selection_index', 'season', 'term', 'selected_models', 'show_ensemble_members', 'nonlinear_pos', 'min_bias_threshold', 'slope_control', 'vmax')
    def get_new_multi_model_scatterplot(self):
        if not self._selection_index:
            return 
        region_names = gdf_regions.iloc[self._selection_index].index.tolist()
        region_name = region_names[0]
        ds_region = data_ensemble_mean.sel(model=self.selected_models, season=self.season, term=self.term, region_id=region_name).squeeze()
        # aspect=1 makes this render as a perfect square. Earlier this was
        # removed because pairing `aspect` with `responsive=True` *and*
        # sizing_mode='stretch_both' made HoloViews stretch height to fill
        # the grid cell, overriding the aspect and overlapping the plots
        # below. Now it's placed with sizing_mode='stretch_width' (see
        # multimodel_view), so width comes from the grid column and height
        # is derived from that width via the aspect ratio - i.e. this plot's
        # own square size is what sets the top block's height, rather than
        # the block dictating an arbitrary height to the plot.
        scatter_opts = dict(toolbar='above', margin=0, responsive=True, aspect=1)

        scatter_overlay = self.get_multi_model_scatter_plot(ds_region, region_name).opts(**scatter_opts)  
        
        return scatter_overlay

    def _get_model_style_mappings(self, model_names):
        style_csv_path = Path(__file__).resolve().parent / 'data' / 'aux' / 'model_styles.csv'
        styles_df = pd.read_csv(style_csv_path)

        markers_mapping_dict = styles_df.set_index('model')['marker'].to_dict()
        colors_mapping_dict = styles_df.set_index('model')['color'].to_dict()

        fallback_markers = ['circle', 'square', 'triangle', 'diamond', 'hex', 'star', 'inverted_triangle', 'plus']
        fallback_colors = ['#50C840', '#4C78A8', '#5EA9D7', '#DB56E4', '#B279A2', '#EABF30', '#E45756', '#72B7B2']
        for index, model_name in enumerate(model_names):
            markers_mapping_dict.setdefault(model_name, fallback_markers[index % len(fallback_markers)])
            colors_mapping_dict.setdefault(model_name, fallback_colors[index % len(fallback_colors)])

        return markers_mapping_dict, colors_mapping_dict

    @param.depends('nonlinear_pos', 'min_bias_threshold', 'slope_control', 'term', 'vmax', 'show_ensemble_members')
    def get_multi_model_scatter_plot(self, ds_region, region, **kwargs):
        # 1. Extract base components
        conversion = ds_region.sel(source='Conversion')
        dynamical = ds_region.sel(source='Dynamical')
        nonlinear = ds_region.sel(source='Non Linear')
        
        # 2. Determine X and Y for classification
        if self.nonlinear_pos == 'Dynamical':
            x_val = conversion
            y_val = dynamical.fillna(0) + nonlinear.fillna(0)
            x_label = f"Conversion {self.term} (%)"
            y_label = f"Dynamical + Non Linear {self.term} (%)"
        else:
            x_val = conversion.fillna(0) + nonlinear.fillna(0)
            y_val = dynamical
            x_label = f"Conversion + Non Linear {self.term} (%)"
            y_label = f"Dynamical {self.term} (%)"
            
        # 3. Create DataFrame for model means
        df = pd.DataFrame({
            'model': ds_region.model.values,
            'Conversion': conversion.values,
            'Dynamical': dynamical.values,
            'Non_Linear': nonlinear.values,
            'X': x_val.values,
            'Y': y_val.values,
            'Net apparent': (conversion + dynamical + nonlinear).values
        })
        
        # 4. Add classification logic (consistent with compute_classified_data_v3)
        def classify(row):
            x, y = row['X'], row['Y']
            if abs(x) + abs(y) <= self.min_bias_threshold: return 'Minimal'
            if abs(x) < self.slope_control * abs(y): return 'Dynamical'
            if abs(y) < self.slope_control * abs(x): return 'Conversion'
            return 'Compounding' if x * y > 0 else 'Compensating'
            
        df['Type'] = df.apply(classify, axis=1)
        
        # 5. Tooltips
        tooltips = f"""
        <div>
            <span style="font-size: 15px; font-weight: bold;">@model</span>
        </div>
        <div><span style="font-size: 12px;">Type: <b>@Type {self.term}</b></span></div>
        <hr>
        <div><span style="font-size: 11px;">{x_label.replace(' (%)','')}: <b>@X{{0.0}}%</b></span></div>
        <div><span style="font-size: 11px;">{y_label.replace(' (%)','')}: <b>@Y{{0.0}}%</b></span></div>
        <hr>
        <div><span style="font-size: 11px;">Conversion: @Conversion{{0.0}}%</span></div>
        <div><span style="font-size: 11px;">Dynamical: @Dynamical{{0.0}}%</span></div>
        <div><span style="font-size: 11px;">Non Linear: @Non_Linear{{0.0}}%</span></div>
        <hr>
        <div><span style="font-size: 11px;"><b>Net apparent {self.term}: @Net apparent{{0.0}}%</b></span></div>
        """
        hover = HoverTool(tooltips=tooltips)
        list_models = df['model'].unique().tolist()
        markers_mapping_dict, colors_mapping_dict = self._get_model_style_mappings(list_models)
        
        df['marker'] = df['model'].map(markers_mapping_dict)
        df['color'] = df['model'].map(colors_mapping_dict)
        
        hover_cols = ['model', 'X', 'Y', 'Conversion', 'Dynamical', 'Non_Linear', 'Net apparent', 'Type']
        df_ens = None

        # 6. Build ensemble members first so each model can share one legend item
        # with its corresponding mean point.
        if self.show_ensemble_members:
            available_member_models = set(data_ensemble_members.model.values.tolist())
            selected_member_models = [m for m in self.selected_models if m in available_member_models]

            if selected_member_models:
                data_ensemble_members_sub = data_ensemble_members.sel(
                    model=selected_member_models,
                    season=self.season,
                    term=self.term,
                    region_id=region
                )
                c_ens = data_ensemble_members_sub.sel(source='Conversion')
                d_ens = data_ensemble_members_sub.sel(source='Dynamical')
                n_ens = data_ensemble_members_sub.sel(source='Non Linear')

                if self.nonlinear_pos == 'Dynamical':
                    x_ens = c_ens
                    y_ens = d_ens + n_ens
                else:
                    x_ens = c_ens + n_ens
                    y_ens = d_ens

                df_ens_x = x_ens.to_dataframe(name='X').reset_index()
                df_ens_y = y_ens.to_dataframe(name='Y').reset_index()
                df_ens = df_ens_x.copy()
                df_ens['Y'] = df_ens_y['Y']
                df_ens['color'] = df_ens['model'].map(colors_mapping_dict)
                df_ens['marker'] = df_ens['model'].map(markers_mapping_dict)

        model_layers = []
        for model_name in list_models:
            model_df = df[df['model'] == model_name]
            mean_layer = model_df.hvplot.scatter(
                x='X',
                y='Y',
                hover_cols=hover_cols,
                tools=[hover],
                color=model_df['color'].iloc[0],
                marker=model_df['marker'].iloc[0],
                size=250,
                line_color='white',
                line_width=1.0,
            ).opts(
                nonselection_alpha=1.0,
                nonselection_line_alpha=1.0,
            ).relabel(model_name)

            if df_ens is None:
                model_layers.append(mean_layer)
                continue

            model_ens_df = df_ens[df_ens['model'] == model_name]
            if model_ens_df.empty:
                model_layers.append(mean_layer)
                continue

            ensemble_layer = model_ens_df.hvplot.scatter(
                x='X',
                y='Y',
                color=model_df['color'].iloc[0],
                marker=model_df['marker'].iloc[0],
                size=30,
                alpha=0.7,
                line_color='#555555',
                line_width=1.2,
                tools=['pan', 'wheel_zoom'],
                hover=False,
            ).opts(
                nonselection_alpha=0.4,
            ).relabel(model_name)

            model_layers.append(ensemble_layer * mean_layer)

        # Render model means as separate labelled layers so the legend shows one
        # entry per model instead of a single unlabeled glyph set.
        scatter = hv.Overlay(model_layers).opts(
            title=f"Multi-model {self.term.capitalize()} Classification\n{self.selected_regions[0]} | {self.season}",
            xlabel=x_label,
            ylabel=y_label,
            xlim=(-max(100, self.vmax), max(100, self.vmax)),
            ylim=(-max(100, self.vmax), max(100, self.vmax)),
            show_legend=True,
            legend_position='bottom',
            responsive=True,
            tools=['pan', 'wheel_zoom', 'save', 'reset',],
        )

        background = self.get_scatter_background()
        return (background * scatter).opts(active_tools=['pan', 'wheel_zoom'], margin=0,
                                           hooks=[self.hook_multi_model_legend],
                                           xlim=(-max(100, self.vmax), max(100, self.vmax)),ylim=(-max(100, self.vmax), max(100, self.vmax)), 
                                           xlabel=x_label,
                                           ylabel=y_label,
                                           title=f"Multi-model {self.term.capitalize()} Classification\n{self.selected_regions[0]} | {self.season}",
                                           legend_position='bottom',
                                           legend_opts={"background_fill_alpha": 0.4, 'spacing':0, 'padding':0, 'margin':1, 'glyph_width': 25, 'glyph_height': 25,
                                                        'title':'Climate Models',"label_standoff": 1,"label_height":1,"orientation":"horizontal",
                                                        "ncols":6, "title_text_font_size":"10pt", "label_text_font_size":"8pt"})

    # OPTIMIZATION 8: Make precursor maps use dynamic tabs
    @param.depends('_selection_index', 'season', 'show_precursors')
    def get_precursor_maps(self):
        """Display precursor maps (U850, V850, Z500) for selected regions in tabs."""
        if not self.show_precursors:
             return #pn.pane.Markdown("### Precursor Maps Disabled\n*Enable 'Show Precursor Maps' in the sidebar to view patterns (may reduce performance)*")
             
        if not self._selection_index:
            return #pn.pane.Markdown("### Precursor maps: No region selected\n*Click on a map or scatter point to see precursor patterns*")

        region_iloc_idxs = self._selection_index
        regions = gdf_regions.iloc[region_iloc_idxs].index.tolist()
        
        try:
            # OPTIMIZATION: Create lazy tab constructors
            def make_precursor_tab(region):
                """Lazy constructor for precursor map tab."""
                return lambda: get_precursor_plot(season=self.season, region=region)
            
            tabs = [(region, make_precursor_tab(region)) for region in regions]
            
            # Create a shared qualitative colorbar
            from bokeh.models import FixedTicker
            dummy_data = pd.DataFrame({'x': [0, 1], 'y': [0, 0], 'z': [-1, 1]})
            dummy_cbar = dummy_data.hvplot.heatmap(
                x='x', y='y', C='z', 
                cmap='RdBu_r', 
                clim=(-1, 1),
                colorbar=True,
                alpha=0,
                frame_height=30, 
                frame_width=1,               
                xaxis=None, yaxis=None,
                clabel='Precursor Anomaly'
            ).opts(
                toolbar=None, 
                colorbar_opts={
                    'ticker': FixedTicker(ticks=[-1, 1]),
                    'major_label_overrides': {-1: '   Negative anomaly', 1: 'Positive anomaly'},
                    'orientation': 'horizontal',
                    'title_text_font_size': '0pt',
                    'bar_line_color': 'black',
                    'height': 15,
                    'width': 400,
                    'padding': 0
                }
            )
            cbar_row = pn.Row(
                pn.Spacer(sizing_mode='stretch_width'), 
                dummy_cbar, 
                pn.Spacer(sizing_mode='stretch_width'), 
                margin=(0, 0, 0, 0),
                min_height=30
            )

            # Use dynamic=True for lazy loading
            return pn.Column(
                pn.pane.Markdown("""
                                 ## Precursor Patterns
                                 Dynamical precursors are weather patterns used to isolate dynamical contributions to changes and biases in heavy precipitation occurrence. They are identified in ERA5 as favouring heavy precipitation and are specific to each region and season.
                                 """, margin=(20, 0, 5, 20)),
                pn.Tabs(*tabs, margin=(0, 0, 0, 20), min_height=400, sizing_mode='scale_width', max_width=1200, dynamic=True),
                cbar_row,
                min_height=450,
                sizing_mode='scale_width',
                max_width=1200
            )
        except Exception as e:
            print(f"Error in get_precursor_maps: {e}")
            import traceback
            traceback.print_exc()
            return pn.pane.Markdown(f"### Error loading maps\n{e}")

    # ------------------------------------------------------------------ #
    # Two-model comparison helpers                                         #
    # ------------------------------------------------------------------ #

    def _get_classified_data_for_model(self, model):
        """Return classified DataFrame for an arbitrary model (uses lru_cache internally)."""
        source_tuple = tuple(self.source) if self.source else ()
        return compute_classified_data_v3(
            model, self.season, self.term, self.nonlinear_pos,
            source_tuple, self.min_bias_threshold, self.slope_control
        )

    def hook_colorbar_only(self, plot, element):
        """Lightweight hook that only repositions and styles the colorbar."""
        if not plot.state:
            return
        for side in ['right', 'left', 'above', 'below']:
            side_layout = getattr(plot.state, side)
            cbars = [r for r in side_layout if 'ColorBar' in str(type(r))]
            for cbar in cbars:
                try:
                    side_layout.remove(cbar)
                    plot.state.add_layout(cbar, 'center')
                    cbar.location = 'top_left'
                    cbar.orientation = 'horizontal'
                    cbar.height = 12
                    cbar.width = 250
                    cbar.title_text_font_size = '9pt'
                    cbar.label_text_font_size = '8pt'
                    cbar.major_tick_out = 3
                    cbar.label_standoff = 3
                    cbar.background_fill_color = 'white'
                    cbar.background_fill_alpha = 0.8
                    cbar.border_line_color = 'grey'
                    cbar.level = 'overlay'
                except Exception:
                    pass

    def _render_comparison_map(self, model, color_col, cmap, clim=None, title=""):
        """Render a read-only (no selection) choropleth map for a specific model."""
        default_xlim = (-11, 30)
        default_ylim = (30, 80)

        df_class = self._get_classified_data_for_model(model)
        gdf = gdf_regions.copy()
        safe_term = self.term.replace(' ', '_')

        if not df_class.empty:
            df_to_map = df_class.set_index('Region')
            gdf[self.term] = gdf.index.map(df_to_map['Selected_Sum'])
            gdf[safe_term] = gdf[self.term]
            gdf['Conversion'] = gdf.index.map(df_to_map['Conversion'])
            gdf['Dynamical'] = gdf.index.map(df_to_map['Dynamical'])
            gdf['Non_Linear'] = gdf.index.map(df_to_map['Non_Linear'])
            gdf['Net apparent'] = gdf.index.map(df_to_map['Net apparent'])
            gdf['Type'] = gdf.index.map(df_to_map['Type']).fillna('No Data')
            gdf['Text_Color'] = gdf.index.map(df_to_map['Text_Color']).fillna('#D3D3D3')
        else:
            for col in [self.term, safe_term, 'Conversion', 'Dynamical', 'Non_Linear', 'Net apparent']:
                gdf[col] = 0
            gdf['Type'] = 'Minimal'
            gdf['Text_Color'] = 'grey'

        gdf.index = gdf.index.rename('Region_Name')
        gdf = gdf.reset_index()
        gdf.loc[:, 'Source'] = 'Net apparent' if len(self.source) == 3 else ' + '.join(self.source)

        value_line = (
            f'<div style="margin-top: 5px;"><span style="font-size: 12px;">'
            f'@Source {self.term}: <b>@{{{safe_term}}}{{0.0}}%</b></span></div>'
            if clim is not None else ""
        )
        tooltips = f"""
        <div>
            <span style="font-size: 15px; color: @Text_Color; font-weight: bold;">@Region_Name</span>
        </div>
        <div><span style="font-size: 12px;">Type: <b>@Type {self.term}</b></span></div>
        {value_line}
        <hr>
        <div><span style="font-size: 11px;">Conversion: @Conversion{{0.0}}%</span></div>
        <div><span style="font-size: 11px;">Dynamical: @Dynamical{{0.0}}%</span></div>
        <div><span style="font-size: 11px;">Non Linear: @Non_Linear{{0.0}}%</span></div>
        <hr>
        <div><span style="font-size: 11px;"><b>Net apparent {self.term}: @Net apparent{{0.0}}%</b></span></div>
        """
        html_hover = HoverTool(tooltips=tooltips)

        plot_opts = dict(
            responsive=True,
            aspect=0.85,
            tools=[html_hover],
            cmap=cmap,
            color=color_col,
            projection=ccrs.PlateCarree(),
            data_aspect=None,
            title=title,
            xlim=default_xlim,
            ylim=default_ylim,
            line_color='black',
            line_width=0.4,
            active_tools=[],
            axiswise=True,
        )
        if clim is not None:
            plot_opts['clim'] = clim
            plot_opts['colorbar'] = True
            plot_opts['hooks'] = [self.hook_colorbar_only]
        else:
            plot_opts['colorbar'] = False
            plot_opts['legend_position'] = 'top_left'

        return gdf.hvplot.polygons(
            crs=ccrs.PlateCarree(),
            color=color_col,
            hover_cols=['Region_Name', 'Source', 'Conversion', 'Dynamical', 'Non_Linear', 'Net apparent', 'Type', 'Text_Color'],
            geo=True
        ).opts(**plot_opts)

    @param.depends('model_a', 'season', 'term', 'source', 'vmax', 'nonlinear_pos', 'min_bias_threshold', 'slope_control')
    def get_comparison_value_map_a(self):
        label = 'Net apparent' if len(self.source) == 3 else ' + '.join(self.source)
        return self._render_comparison_map(
            self.model_a, self.term, 'BrBG', (-self.vmax, self.vmax),
            f"{self.model_a} | {self.season}\n{label} {self.term} (%)"
        )

    @param.depends('model_a', 'season', 'term', 'nonlinear_pos', 'min_bias_threshold', 'slope_control')
    def get_comparison_type_map_a(self):
        return self._render_comparison_map(
            self.model_a, 'Type', self.sector_cmap, None,
            f"{self.term.capitalize()} classification\n{self.model_a} | {self.season}"
        )

    @param.depends('model_b', 'season', 'term', 'source', 'vmax', 'nonlinear_pos', 'min_bias_threshold', 'slope_control')
    def get_comparison_value_map_b(self):
        label = 'Net apparent' if len(self.source) == 3 else ' + '.join(self.source)
        return self._render_comparison_map(
            self.model_b, self.term, 'BrBG', (-self.vmax, self.vmax),
            f"{self.model_b} | {self.season}\n{label} {self.term} (%)"
        )

    @param.depends('model_b', 'season', 'term', 'nonlinear_pos', 'min_bias_threshold', 'slope_control')
    def get_comparison_type_map_b(self):
        return self._render_comparison_map(
            self.model_b, 'Type', self.sector_cmap, None,
            f"{self.model_b} | {self.season}\n{self.term.capitalize()} classification"
        )

    @param.depends('model_a', 'model_b', 'season', 'term', 'source', 'vmax', 'nonlinear_pos', 'min_bias_threshold', 'slope_control')
    def get_difference_map(self):
        source_tuple = tuple(self.source) if self.source else ()
        label = 'Net apparent' if len(self.source) == 3 else ' + '.join(self.source)

        df_a = compute_classified_data_v3(
            self.model_a, self.season, self.term, self.nonlinear_pos,
            source_tuple, self.min_bias_threshold, self.slope_control
        )
        df_b = compute_classified_data_v3(
            self.model_b, self.season, self.term, self.nonlinear_pos,
            source_tuple, self.min_bias_threshold, self.slope_control
        )

        gdf = gdf_regions.copy()
        if not df_a.empty and not df_b.empty:
            da = df_a.set_index('Region')['Selected_Sum']
            db = df_b.set_index('Region')['Selected_Sum']
            gdf['diff'] = gdf.index.map(da - db)
        else:
            gdf['diff'] = np.nan

        gdf.index = gdf.index.rename('Region_Name')
        gdf = gdf.reset_index()

        tooltips = f"""
        <div>
            <span style="font-size: 15px; font-weight: bold;">@Region_Name</span>
        </div>
        <div><span style="font-size: 12px;">{label} {self.term} difference
            ({self.model_a} − {self.model_b}): <b>@diff{{0.0}}%</b></span></div>
        """
        html_hover = HoverTool(tooltips=tooltips)

        return gdf.hvplot.polygons(
            crs=ccrs.PlateCarree(),
            color='diff',
            hover_cols=['Region_Name', 'diff'],
            geo=True
        ).opts(
            responsive=True,
            aspect=0.85,
            tools=[html_hover],
            cmap='PRGn_r',
            clim=(-self.vmax / 2, self.vmax / 2),
            colorbar=True,
            projection=ccrs.PlateCarree(),
            title=(f"{label} {self.term} difference (%)\n"
                   f"{self.model_a} − {self.model_b} | {self.season}"),
            xlim=(-11, 30),
            ylim=(30, 80),
            line_color='black',
            line_width=0.4,
            active_tools=[],
            axiswise=True,
            hooks=[self.hook_colorbar_only]
        )

    @param.depends('model_a', 'model_b', 'season', 'term', 'nonlinear_pos', 'min_bias_threshold', 'slope_control')
    def get_agreement_map(self):
        """Two-color map: same classification vs different classification between model A and B."""
        source_tuple = tuple(self.source) if self.source else ()

        df_a = compute_classified_data_v3(
            self.model_a, self.season, self.term, self.nonlinear_pos,
            source_tuple, self.min_bias_threshold, self.slope_control
        )
        df_b = compute_classified_data_v3(
            self.model_b, self.season, self.term, self.nonlinear_pos,
            source_tuple, self.min_bias_threshold, self.slope_control
        )

        gdf = gdf_regions.copy()
        if not df_a.empty and not df_b.empty:
            type_a = gdf.index.map(df_a.set_index('Region')['Type']).fillna('No Data')
            type_b = gdf.index.map(df_b.set_index('Region')['Type']).fillna('No Data')
            gdf['Agreement'] = np.where(type_a == type_b, 'Same', 'Different')
            gdf['Type_A'] = type_a
            gdf['Type_B'] = type_b
        else:
            gdf['Agreement'] = 'No Data'
            gdf['Type_A'] = 'No Data'
            gdf['Type_B'] = 'No Data'

        gdf.index = gdf.index.rename('Region_Name')
        gdf = gdf.reset_index()

        tooltips = f"""
        <div>
            <span style="font-size: 15px; font-weight: bold;">@Region_Name</span>
        </div>
        <div><span style="font-size: 12px;">Agreement: <b>@Agreement</b></span></div>
        <hr>
        <div><span style="font-size: 11px;">{self.model_a}: @Type_A</span></div>
        <div><span style="font-size: 11px;">{self.model_b}: @Type_B</span></div>
        """
        html_hover = HoverTool(tooltips=tooltips)

        return gdf.hvplot.polygons(
            crs=ccrs.PlateCarree(),
            color='Agreement',
            hover_cols=['Region_Name', 'Agreement', 'Type_A', 'Type_B'],
            geo=True
        ).opts(
            responsive=True,
            aspect=0.85,
            tools=[html_hover],
            cmap={'Same': '#4CAF50', 'Different': '#BDBDBD'},
            colorbar=False,
            legend_position='top_left',
            projection=ccrs.PlateCarree(),
            title=(f"{self.term.capitalize()} classification agreement\n"
                   f"{self.model_a} vs {self.model_b} | {self.season}"),
            xlim=(-11, 30),
            ylim=(30, 80),
            line_color='black',
            line_width=0.4,
            active_tools=[],
            axiswise=True,
        )

    def get_sidebar_footer(self):
        return pn.pane.Markdown(
            "---\n**Reference:**  \nOldham-Dorrington, J., Li, C., Sobolowski, S., & Guillaume-Castel, R. (2026). Understanding biases and changes in European heavy precipitation using dynamical flow precursors. Weather and Climate Dynamics, 7(2), 633-657. <a href='https://wcd.copernicus.org/articles/7/633/2026/' target='_blank'>https://wcd.copernicus.org/articles/7/633/2026/</a>\n\nRobin Guillaume-Castel & Joshua Oldham-Dorrington - 2026",
            sizing_mode='stretch_width',
            margin=(10, 10),
            styles={'font-size': '0.84em'}
        )
    def get_intro_sidebar(self):
        return pn.Column(
            pn.pane.Markdown(
                "### Change climate model, season and metric of interest here.",
                margin=(20, 10, 5, 30)),
            pn.Row(pn.Param(self.param, parameters=['season'],show_name=False, width=250),
                   pn.widgets.TooltipIcon(value=tooltips_strings.season_dropdown)),
            pn.Row(pn.Param(self.param, parameters=['model'],show_name=False, width=250),
                   pn.widgets.TooltipIcon(value=tooltips_strings.model_dropdown)),
            pn.Row(pn.Param(self.param, parameters=['term'],show_name=False, width=250),
                   pn.widgets.TooltipIcon(value=tooltips_strings.term_dropdown)),
            pn.layout.VSpacer(),
            self.get_sidebar_footer(),
            sizing_mode='stretch_both'
        )
    def get_single_model_sidebar(self):
        return pn.Column(
            pn.pane.Markdown(
                "### Change parameters for plots in the multi-region tab here.",
                margin=(20, 10, 5, 30)),
            pn.Row(pn.Param(self.param, parameters=['season'],show_name=False, width=250),
                   pn.widgets.TooltipIcon(value=tooltips_strings.season_dropdown)),
            pn.Row(pn.Param(self.param, parameters=['model'],show_name=False, width=250),
                   pn.widgets.TooltipIcon(value=tooltips_strings.model_dropdown)),
            pn.Row(pn.Param(self.param, parameters=['term'],show_name=False, width=250,),
                   pn.widgets.TooltipIcon(value=tooltips_strings.term_dropdown)),
            pn.Row(pn.Param(self.param, parameters=['show_precursors'],show_name=False, width=250,
                            widgets={'show_precursors': {'type': pn.widgets.Switch, 'align': 'start'},}),
                   pn.widgets.TooltipIcon(value=tooltips_strings.Show_Precursor_Maps)),
            pn.Column(
                pn.Card(
                    pn.Column(
                        pn.widgets.TooltipIcon(value=tooltips_strings.Selected_Regions),
                        pn.Param(
                            self.param,
                            parameters=['selected_regions'],
                            widgets={'selected_regions': {'height': 300}},
                            show_name=False
                        ),
                        margin=(10, 5)
                    ),
                    title="Regions selected",
                    collapsible=True,
                    collapsed=True
                ),

                pn.Card(
                    pn.Column(
                        pn.Row(pn.Param(self.param, parameters=['source'],show_name=False, width=230,
                                         widgets={ 'source': {'type': pn.widgets.MultiChoice }}),
                            pn.widgets.TooltipIcon(value=tooltips_strings.Source_Selection)),
                        pn.Row(pn.Param(self.param, parameters=['vmax'],show_name=False, width=230,
                                         widgets={ 'vmax': {'type': pn.widgets.FloatInput}}),
                            pn.widgets.TooltipIcon(value=tooltips_strings.colormap_scaler)),
                        margin=(10, 5)
                    ),
                    title="Maps parameters",
                    collapsible=True,
                    collapsed=True
                ),

                pn.Card(
                    pn.Column(
                        pn.Row(pn.Param(self.param, parameters=['bar_sort'], show_name=False, width=230,
                                         widgets={'bar_sort': {'type': pn.widgets.Select}})),
                        pn.Row(pn.Param(self.param, parameters=['bar_sort_ascending'], show_name=False, width=230,
                                         widgets={'bar_sort_ascending': {'type': pn.widgets.Switch, 'align': 'start'}})),
                        margin=(10, 5)
                    ),
                    title="Bar plot parameters",
                    collapsible=True,
                    collapsed=True,
                ),

                pn.Card(
                    pn.Column(
                        pn.Row(pn.Param(self.param, parameters=['nonlinear_pos'],show_name=False, width=230,
                                         widgets={ 'nonlinear_pos': {'type': pn.widgets.Select}}),
                            pn.widgets.TooltipIcon(value=tooltips_strings.group_nonlinear_term)),
                        pn.Row(pn.Param(self.param, parameters=['min_bias_threshold'],show_name=False, width=230,
                                         widgets={ 'min_bias_threshold': {'type': pn.widgets.IntInput}}),
                            pn.widgets.TooltipIcon(value=tooltips_strings.Minimal_difference_thresh)),
                        pn.Row(pn.Param(self.param, parameters=['slope_control'],show_name=False, width=230,
                                         widgets={ 'slope_control': {'type': pn.widgets.FloatInput, 'step': 0.01}}),
                            pn.widgets.TooltipIcon(value=tooltips_strings.sector_slope_thresh)),
                        pn.Row(pn.Param(self.param, parameters=['diag_interval'],show_name=False, width=230,
                                         widgets={ 'diag_interval': {'type': pn.widgets.IntInput}}),
                            pn.widgets.TooltipIcon(value=tooltips_strings.diag_interval)),
                        pn.Row(pn.Param(self.param, parameters=['show_diag_lines'], show_name=False, width=230,
                                         widgets={'show_diag_lines': {'type': pn.widgets.Switch, 'align': 'start'}})),
                        pn.Row(pn.Param(self.param, parameters=['show_diamonds'], show_name=False, width=230,
                                         widgets={'show_diamonds': {'type': pn.widgets.Switch, 'align': 'start'}})),
                    ),
                    title="Scatter parameters (advanced)",
                    collapsible=True,
                    collapsed=True,
                ),
                sizing_mode="stretch_width"
            ),
            pn.layout.VSpacer(),
            self.get_sidebar_footer(),
            sizing_mode='stretch_both'
        )

    def get_multi_model_sidebar(self):
        return pn.Column(
            pn.pane.Markdown(
                "### Change parameters for plots in the multi-model tab here.",
                margin=(20, 10, 5, 30)),
            pn.Row(pn.Param(self.param, parameters=['season'],show_name=False, width=250),
                   pn.widgets.TooltipIcon(value=tooltips_strings.season_dropdown)),
            pn.Row(pn.Param(self.param, parameters=['term'],show_name=False, width=250),
                   pn.widgets.TooltipIcon(value=tooltips_strings.term_dropdown)),
            pn.Row(pn.Param(self.param, parameters=['selected_models'],show_name=False, width=250,
                            widgets={'selected_models': {'type': pn.widgets.MultiChoice}}),
                   pn.widgets.TooltipIcon(value=tooltips_strings.model_dropdown)),
            pn.Row(pn.Param(self.param, parameters=['show_ensemble_members'],show_name=False, width=250,
                            widgets={'show_ensemble_members': {'type': pn.widgets.Switch, 'align': 'start'},}),
                   pn.widgets.TooltipIcon(value=tooltips_strings.show_ens)),
            pn.Row(pn.Param(self.param, parameters=['show_precursors'],show_name=False, width=250,
                            widgets={'show_precursors': {'type': pn.widgets.Switch, 'align': 'start'},}),
                   pn.widgets.TooltipIcon(value=tooltips_strings.Show_Precursor_Maps)),
            
            
            pn.Column(
                pn.Card(
                    pn.Column(
                        pn.widgets.TooltipIcon(value=tooltips_strings.Selected_Regions_unique),
                        pn.Param(
                            self.param,
                            parameters=['selected_regions'],
                            widgets={'selected_regions': {'height': 300}},
                            show_name=False
                        ),
                        margin=(10, 5)
                    ),
                    title="Regions selected",
                    collapsible=True,
                    collapsed=True
                ),
                pn.Card(
                    pn.Column(
                        pn.Row(pn.Param(self.param, parameters=['bar_sort'], show_name=False, width=230,
                                         widgets={'bar_sort': {'type': pn.widgets.Select}})),
                        pn.Row(pn.Param(self.param, parameters=['bar_sort_ascending'], show_name=False, width=230,
                                         widgets={'bar_sort_ascending': {'type': pn.widgets.Switch, 'align': 'start'}})),
                        margin=(10, 5)
                    ),
                    title="Bar plot parameters",
                    collapsible=True,
                    collapsed=True,
                ),
                pn.Card(
                    pn.Column(
                        pn.Row(pn.Param(self.param, parameters=['nonlinear_pos'],show_name=False, width=230,
                                         widgets={ 'nonlinear_pos': {'type': pn.widgets.Select}}),
                            pn.widgets.TooltipIcon(value=tooltips_strings.group_nonlinear_term)),
                        pn.Row(pn.Param(self.param, parameters=['min_bias_threshold'],show_name=False, width=230,
                                         widgets={ 'min_bias_threshold': {'type': pn.widgets.IntInput}}),
                            pn.widgets.TooltipIcon(value=tooltips_strings.Minimal_difference_thresh)),
                        pn.Row(pn.Param(self.param, parameters=['slope_control'],show_name=False, width=230,
                                         widgets={ 'slope_control': {'type': pn.widgets.FloatInput, 'step': 0.01}}),
                            pn.widgets.TooltipIcon(value=tooltips_strings.sector_slope_thresh)),
                        pn.Row(pn.Param(self.param, parameters=['diag_interval'],show_name=False, width=230,
                                         widgets={ 'diag_interval': {'type': pn.widgets.IntInput}}),
                            pn.widgets.TooltipIcon(value=tooltips_strings.diag_interval)),
                        pn.Row(pn.Param(self.param, parameters=['show_diag_lines'], show_name=False, width=230,
                                         widgets={'show_diag_lines': {'type': pn.widgets.Switch, 'align': 'start'}})),
                        pn.Row(pn.Param(self.param, parameters=['show_diamonds'], show_name=False, width=230,
                                         widgets={'show_diamonds': {'type': pn.widgets.Switch, 'align': 'start'}})),
                    ),
                    title="Scatter plot parameters (advanced)",
                    collapsible=True,
                    collapsed=True,
                ),
                sizing_mode="stretch_width"
            ),
            pn.layout.VSpacer(),
            self.get_sidebar_footer(),
            sizing_mode='stretch_both'
        )

    def _swap_models(self, event=None):
        self.model_a, self.model_b = self.model_b, self.model_a

    def get_comparison_sidebar(self):
        swap_btn = pn.widgets.Button(name='Swap A ⇄ B', button_type='default', width=100)
        swap_btn.on_click(self._swap_models)
        return pn.Column(
            pn.pane.Markdown(
                "### Compare two climate models side by side.",
                margin=(20, 10, 5, 30)),
            pn.Row(pn.Param(self.param, parameters=['season'], show_name=False, width=250),
                   pn.widgets.TooltipIcon(value=tooltips_strings.season_dropdown)),
            pn.Row(pn.Param(self.param, parameters=['term'], show_name=False, width=250),
                   pn.widgets.TooltipIcon(value=tooltips_strings.term_dropdown)),
            pn.Row(pn.Param(self.param, parameters=['model_a'], show_name=False, width=250),
                   pn.widgets.TooltipIcon(value=tooltips_strings.model_dropdown)),
            pn.Row(pn.Param(self.param, parameters=['model_b'], show_name=False, width=250),
                   pn.widgets.TooltipIcon(value=tooltips_strings.model_dropdown)),
            pn.Row(swap_btn, align='center', margin=(2, 10)),
            pn.Card(
                pn.Column(
                    pn.Row(pn.Param(self.param, parameters=['source'], show_name=False, width=230,
                                     widgets={'source': {'type': pn.widgets.MultiChoice}}),
                        pn.widgets.TooltipIcon(value=tooltips_strings.Source_Selection)),
                    pn.Row(pn.Param(self.param, parameters=['vmax'], show_name=False, width=230,
                                     widgets={'vmax': {'type': pn.widgets.FloatInput}}),
                        pn.widgets.TooltipIcon(value=tooltips_strings.colormap_scaler)),
                    margin=(10, 5)
                ),
                title="Maps parameters",
                collapsible=True,
                collapsed=True
            ),
            pn.layout.VSpacer(),
            self.get_sidebar_footer(),
            sizing_mode='stretch_both'
        )

    def comparison_view(self):
        maps_a = pn.Tabs(
            ('Value map', pn.panel(self.get_comparison_value_map_a, sizing_mode='scale_width')),
            ('Classification', pn.panel(self.get_comparison_type_map_a, sizing_mode='scale_width')),
            sizing_mode='scale_width',
        )
        maps_b = pn.Tabs(
            ('Value map', pn.panel(self.get_comparison_value_map_b, sizing_mode='scale_width')),
            ('Classification', pn.panel(self.get_comparison_type_map_b, sizing_mode='scale_width')),
            sizing_mode='scale_width',
        )
        header_a = pn.pane.Markdown(
            pn.bind(lambda m: f"## {m}", self.param.model_a),
            margin=(5, 0, 0, 5)
        )
        header_b = pn.pane.Markdown(
            pn.bind(lambda m: f"## {m}", self.param.model_b),
            margin=(5, 0, 0, 5)
        )
        return pn.Column(
            pn.pane.Markdown("""
                             # Two-model comparison tab

                             Compare the heavy precipitation decomposition maps for two different climate models side by side.
                             Select both models, the season and metric in the sidebar. The bottom map shows the pointwise difference (Model A − Model B).
                             """),
            pn.Row(
                pn.Column(
                    header_a,
                    maps_a,
                    sizing_mode='scale_width',
                ),
                pn.Column(
                    header_b,
                    maps_b,
                    sizing_mode='scale_width',
                ),
                sizing_mode='stretch_width',
                max_width=1200,
            ),
            pn.pane.Markdown("### Difference & Classification Agreement", margin=(20, 0, 5, 5)),
            pn.Row(
                pn.panel(self.get_difference_map, loading_indicator=True, sizing_mode='scale_width'),
                pn.panel(self.get_agreement_map, loading_indicator=True, sizing_mode='scale_width'),
                sizing_mode='stretch_width',
                max_width=1200,
            ),
            pn.Spacer(height=200),
            sizing_mode='stretch_width',
            name="2-Model comparison",
        )

    def intro_view(self):
        return pn.Column(
            # pn.pane.Markdown(f"# Introduction page"),
            # pn.pane.Markdown(f"### Maps of {self.term}", margin=(0, 0, 10, 0)),
            pn.Row(
                pn.pane.Markdown(f"""
                                # Welcome to our explorer tool!
                                ### This webpage visualises biases and projected future changes in daily regional heavy precipitation within global climate models. 

                                To better understand the scenarios these models describe and how we should interpret them, we use a decomposition approach, breaking down the occurrence of heavy rainfall into contributions from different scales and weather patterns. Our decomposition, <a href='https://egusphere.copernicus.org/preprints/2025/egusphere-2025-4977/' target='_blank'>described in our recent paper</a>, aims to improve our understanding of *why* a model produces heavy precipitation. 
                                The probability of daily heavy precipitation is broken down into a **dynamical contribution** which quantifies the impact that the frequency of rainfall-favouring synoptic weather patterns has on heavy precipitation, and a **conversion contribution** which quantifies how likely the model is to actually simulate heavy precipitation during a given weather pattern. Finally, a **non-linear contribution** captures interactions between these two effects.
                                
                                On the right you can see the overall biases in wintertime heavy precipitation occurrence that we have computed for the CESM2 climate model. The *multi-region* tab can be used to gain a pan-european perspective on biases and forced changes in heavy precipitation for a particular model, and their decomposed contributions. The *multi-model* tab can be used to compare these metrics across multiple models for a selected of interest. To learn more check the tooltips or, for more details, read the papers cited in the sidebar.
                                """,
                                  ),
                pn.panel(self.get_value_map_simple_tooltip, sizing_mode='scale_width'),  # Removed loading_indicator
                
            ),
            pn.Card(
                pn.pane.Markdown("""
                                ### Heavy precipitation event
                                A day where total precipitation averaged over a region is greater than a threshold value. Our threshold is the 95th percentile of daily total precipitation for that region and season as estimated from the ERA5 reanalysis over 1979-2014. In other words, one of the 4 or 5 heaviest rainfall events in a typical season within recent decades. 
                                 
                                ### <u>Bias</u>
                                The difference in the occurrence of heavy precipitation between a model's historical simulation/s and ERA5 over the period 1979-2014. Some apparent `biases' may be the result of sampling variability rather than a genuine model deficiency, especially for single-member or small-ensemble simulations.  
                                 
                                ### <u>Uncalibrated Change</u>
                                The difference in the occurrence of heavy precipitation between a model's SSP370 scenario simulations over 2065-2100 and its historical simulations over the period 1979-2014. As for biases, sampling variability can impact projected trends in some cases.
                                 
                                ### <u>Change</u>
                                The difference between SSP370 and historical heavy precipitation occurrence, as for the Uncalibrated Change, but with estimated distortions to the true forced change removed, which arise from flow- and scale-dependent biases. These changes in rainfall occurrence are more physically consistent futures for our present climate than the Uncalibrated Changes, but there are methodological caveats: see the paper for details. 
                                 
                                ### <u>Dynamical Bias/Change</u>
                                Related to changes in weather patterns on the synoptic scale: features between 100 and 1000 kilometres in scale and with evolution timescales of 1-7 days. Our approach is based on 'flow precursors': algorithmically determined weather patterns that are associated with heavy precipitation in today's climate.
                                 
                                ### <u>Conversion Bias/Change</u>
                                Just because the synoptic weather conditions favours heavy precipitation does not mean it will occur: mesoscale and microphysical processes, thermodynamics, land-surface interactions and aerosol effects can all impact the conversion of dynamical forcing into surface precipitation. These many factors are aggregated into a single Conversion contribution in our approach.
                                 
                                ### <u>Nonlinear Bias/Change</u>
                                The easiest case to consider for explaining nonlinear contributions is for a model which produces precipitation-favouring dynamical conditions too frequently and then moreover is too likely to produce heavy precipitation during these conditions. Each of these biases individually would result in a positive total bias in heavy precipitation occurrence. Taken together they reinforce eachother, creating a larger total bias than the sum of their parts. This is the nonlinear contribution.
                                """),
                title="Quick Glossary of Terms",
                collapsed=True
            ),
            pn.Spacer(height=200),
            max_width=1200,                # stops growing beyond this
            # max_height=900,                # removed to allow card to expand downward
            sizing_mode='stretch_width',
            name="Introduction page",
        )
    
    @param.depends('term')
    def multiregion_view(self):
        scatter_pane = pn.Column(
            pn.panel(self.get_scatter_plot, sizing_mode='scale_width'),  # Removed loading_indicator
            margin=(0, 0, 0, 5),
            sizing_mode='scale_width'
        )
        
        def make_tab_row(map_func):
            return pn.Row(
                pn.panel(map_func, sizing_mode='scale_width'),  # Removed loading_indicator
                pn.Spacer(width=20), 
                scatter_pane, 
                sizing_mode='scale_width', 
                max_width=1200
            )

        map_tabs = pn.Tabs(
            (f'Heavy precip. occurrence {self.term}', make_tab_row(self.get_value_map)),
            (f'Classification of {self.term}', make_tab_row(self.get_type_map)),
            margin=(0, 0, 0, 20),
            sizing_mode='scale_width',
            max_width=1200
        )
        
        # Loading indicator that shows during sync
        @pn.depends(self.param._is_syncing)
        def loading_overlay(_is_syncing):
            if _is_syncing:
                return pn.pane.Markdown("**⟳ Updating plots...**")
            return pn.pane.Markdown("")
        
        return pn.Column(
            pn.pane.Markdown(f"""
                             # Multi-region tab

                             Here, you can explore the heavy precipitation decomposition for a single model and season across all European regions.
                             <b>Click on a region</b> and explore more details about what the selcted model does there. You can select multiple regions by pressing cmd or ctrl when clicking and compare them in the bar plot below. Net apparent bias/change is visualised by default: to see individual terms, modify the map parameters in the sidebar. 
                             """),
            
            map_tabs,
            pn.panel(self.get_bar_plot),  # Removed loading_indicator - now super fast
            pn.panel(self.get_precursor_maps, loading_indicator=True),  # Keep only here
            pn.Spacer(height=200),
            sizing_mode='stretch_width',
            name="Multi-region focus",
        )

    def multimodel_view(self):
        # Layout for the multi-model tab, matching the requested weighting
        # (top block : b : B = 4 : 1 : 3):
        #
        #   s s s m m   \
        #   s s s m m    \
        #   s s s m m     top block
        #   s s s p p    /
        #   b b b b b   -- totals
        #   B B B B B  \
        #   B B B B B   > decomposition
        #   B B B B B  /
        #
        # s = scatterplot, m = selector map, p = pie chart,
        # b = multi-model net-apparent totals, B = multi-model decomposition.
        #
        # Previous version used a plain flexbox pn.Row (via `styles={'flex':
        # ...}`) for the top block, hoping CSS flex-grow would give the
        # scatter 3/5 of the row's width and let the map+pie column stretch
        # to match its height. In practice that squished the scatter: with
        # `flex-basis: 0%`, the browser lays the column out at ~0 width on
        # the first pass, and the square (aspect=1, width-driven) HoloViews
        # plot locks its height to that first-pass width before the flex
        # layout settles into its final size - so it ends up much smaller
        # than intended, which is also why its height only matched the map
        # alone rather than map+pie combined (that arithmetic coincidence
        # was really "scatter got squished down to roughly map's height").
        #
        # GridSpec doesn't have that race: it sets each cell's pixel width
        # directly via CSS grid-template-columns before content mounts, so
        # the square scatter (sizing_mode='stretch_width', aspect=1) always
        # knows its real column width up front. The only thing that was
        # wrong with the earlier GridSpec version was the total `height` in
        # pixels being computed from an assumed 1400px design width - but
        # main_content actually caps everything at max_width=1200. Fixing
        # that one number back to 1200 makes the top block's height line up
        # with the scatter's real square size, and map+pie now fill exactly
        # that same cell (stretch_both) instead of guessed fixed heights.
        _MAX_W = 1200
        _scatter_col_width = _MAX_W * (3 / 5) - 15   # cols 0:3 of 5, minus right margin
        _row_unit = _scatter_col_width / 4            # top block = 4 row-units tall
        _top_h = _row_unit * 4                          # top block
        _b_h = _row_unit * 1                             # net-apparent totals
        _B_h = _row_unit * 3                             # decomposition
        _total_h = int(_top_h + _b_h + _B_h)

        layout = pn.GridSpec(
            sizing_mode='stretch_width',
            height=_total_h,
            max_width=_MAX_W,
            margin=(10, 0, 0, 0),
        )

        layout[0:4, 0:3] = pn.panel(
            self.get_new_multi_model_scatterplot, sizing_mode='stretch_width',
            margin=(5, 15, 15, 0)
        )
        layout[0:3, 3:5] = pn.panel(
            self.get_selector_map, sizing_mode='stretch_both',
            margin=(5, 0, 10, 15)
        )
        layout[3:4, 3:5] = pn.panel(
            self.get_classification_pie_chart, sizing_mode='stretch_both',
            margin=(5, 0, 15, 15)
        )
        layout[4:5, 0:5] = pn.panel(
            self.get_multi_model_bar_total, sizing_mode='stretch_both',
            margin=(15, 0, 10, 0)
        )
        layout[5:8, 0:5] = pn.panel(
            self.get_multi_model_bar_decomp, sizing_mode='stretch_both',
            margin=(10, 0, 10, 0)
        )

        return pn.Column(
            pn.pane.Markdown(f"""
                             # Multi-model tab

                             Here, you can explore the heavy precipitation decomposition for a single European region and season across multiple climate models.
                             <b>Click on a region</b> in the map to select it, and explore how different models compare in the scatter and bar plots. You can select multiple models in the sidebar to compare them, and toggle ensemble members to see the spread within each model. Net apparent bias/change is visualised by default: to see individual terms, modify the map parameters in the sidebar.
                             """),

            pn.Column(
                layout,
                pn.panel(self.get_precursor_maps, loading_indicator=True),
                pn.Spacer(height=200),
                sizing_mode='stretch_width',
            ),
            sizing_mode='stretch_width',
            name="Multi-model focus"
        )
    



app_compare = CMIPApp()
app_intro = CMIPApp()
app_single = CMIPApp()
app_multi = CMIPApp()

title_intro = "CMIP6 European Heavy Rainfall Explorer - Introduction"
title_singlemodel = pn.pane.HTML('<span title="Tooltip for Tab 1">Tab 1</span>')
title_multimodel = pn.pane.HTML('<span title="Tooltip for Tab 2">Tab 2</span>')

main_tabs = pn.Tabs(

    ("Introduction page", app_intro.intro_view), 
    ("Multi-region tab", app_single.multiregion_view),
    ("Multi-model tab", app_multi.multimodel_view()),
    ("2-Model comparison", app_compare.comparison_view()),
    
    stylesheets=[active_tab_css]
)

main_content = pn.Column(
    # pn.pane.Markdown("""
                    #  Some common text here.
                    #  """, margin=(0, 10, 10, 10)),
    main_tabs,
    sizing_mode='stretch_width',
    max_width=1200,
    margin=(20, 0, 20, 0)
)

@pn.depends(main_tabs.param.active)
def dynamic_sidebar(active_index):
    if active_index == 0:
        return app_intro.get_intro_sidebar()
    elif active_index == 1:
        return app_single.get_single_model_sidebar()
    elif active_index == 2:
        return app_multi.get_multi_model_sidebar()
    else:
        return app_compare.get_comparison_sidebar()


app = pn.template.MaterialTemplate(
    site="Decomposing heavy precipitation in CMIP6 using dynamical precursors",
    title="",
    sidebar=[dynamic_sidebar],
    sidebar_width=320,
    main=[main_content],
)
app.servable()