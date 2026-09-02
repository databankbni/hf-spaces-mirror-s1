NEW TEXT AND NAME CHANGES:

title: Decomposing heavy precipitation in CMIP6 using dynamical precursors
Undertext: This webpage visualises biases and projected future changes in daily regional heavy precipitation. To better understand these results we use a decomposition approach to understand *why* a model produces heavy precipitation. The chance of heavy precipitation is broken down into a **dynamical contribution** which quantifies the role of synoptic weather patterns that favour rainfall, and a **conversion contribution** which quantifies the chance that this synoptic forcing converts into a heavy precipitation event. The *multi-region* tab below can be used to gain a pan-european perspective on heavy precipitation for a particular model, while the *multi-model* tab can be used to compare many models for a region of interest. To learn more, check the tooltips, or read \url{our paper}[].


term_dropdown: Metric(?)
Bias (vs ERA5, 1979-2014)
Change (2065-2100 vs 1979-2014)
Uncalibrated Change (2065-2100 vs 1979-2014)

colormap_scaler: Colorbar limits [and display with % on the end]

scatter_tab: Scatter parameters (advanced)
    Group non-linear term with:
    Minimal difference threshold (%)
    Sector slope threshold (ratio)
    Lines of constant apparent bias every (%)
    Lines of constant absolute bias every (%)


Bar chart title:
** Decomposition for Selected Regions (**)

Multi-Region tab

Multi-Model tab

Values tab -> Heavy precip. Occurrence

values_colorbar_label: Relative bias/change/uncalibrated change in heavy precip. occurrence.


TOOLTIP TEXT


name: model_dropdown
tooltip: Specify the climate model to use. Data is taken from historical and SSP3.70 scenario runs.

name: season_dropdown
tooltip: Specify the calendar season.

name: term_dropdown: 
All metrics show change in heavy precipitation occurrence.
    Bias: Difference between historical simulation and ERA5.
    Change: Predicted change between historical and SSP3.70 simulations, with estimated impact of biases removed. 
    Uncalibrated Change: Predicted change between historical and SSP3.70 simulations, without calibration.

colormap_scaler: Sets the limits for all figures. The units are relative change in heavy precipitation occurrence. For example,as the chance of heavy precipitation is defined as 0.05/day in ERA5, a +20% change indicates a chance of 0.06/day.

Show Precursor Maps: Weather patterns used to isolate dynamical contributions, identified in ERA5 as favouring heavy precipitation. These are specific to each region and season.

Selected Regions: Regions were defined algorithmically by grouping locations with shared precipitation variability in ERA5. Names are approximate and no comments on geopolitical borders are intended.


name: group_nonlinear_term
tooltip: Specifies whether the nonlinear contribution should be added to the conversion or dynamical contribution for classification.

name: Minimal_difference_thresh
tooltip: Biases/changes under this threshold will be classed as `minimal'.

name: sector_slope_thresh
tooltip: Determines the extent of the Conversion and Dynamical categories. Lower values will lead to more Compounding or Cancelling categorisations.

name: show_ens
tooltip: Add metrics computed on individual members to the scatter plot for models with multiple historical and scenario realisations.

Category tooltips:
Minimal Bias: Model heavy precip. is a close match to reanalysis. \n Both dynamical and conversion biases are small.

Dynamical Bias (top): The precursor patterns that drive heavy precip. occur too frequently in the model.

Dynamical Bias (bottom): The precursor patterns that drive heavy precip. occur too rarely in the model.

Conversion Bias (left): The model is less likely to produce heavy precip. for a given precursor pattern than in reanalysis. 

Conversion Bias (right): The model is more likely to produce heavy precip. for a given precursor pattern than in reanalysis. 

Compounding Bias (upper): The precursor patterns that drive heavy precip. occur too frequently and are more likely to produce heavy precip. when they occur than in reanalysis.

Compounding Bias (lower): The precursor patterns that drive heavy precip. occur too rarely and are less likely to produce heavy precip. when they do occur than in reanalysis.

Compensating Bias (upper): The precursor patterns that drive heavy precip. occur too frequently but are less likely to produce heavy precip. when they do occur than in reanalysis.


Compensating Bias (lower): The precursor patterns that drive heavy precip. occur too rarely but are more likely to produce heavy precip. when they do occur than in reanalysis.


Minimal Trend: The model projects that future heavy precip. will not change substantially.

Dynamical Trend (top): The model projects that the precursor patterns that drive heavy precip. will occur more frequently in the future.

Dynamical Trend (bottom): The model projects that the precursor patterns that drive heavy precip. will occur less frequently in the future.

Conversion Trend (left): The model projects that for the same precursor pattern, heavy precip. will become less likely in the future.

Conversion Trend (right): The model projects that for the same precursor pattern, heavy precip. will become more likely in the future.

Compounding Trend (upper): The model projects that the precursor patterns driving heavy precip. will become more frequent and become more likely to produce heavy precip. in the future.

Compounding Trend (lower): The model projects that the precursor patterns driving heavy precip. will become less frequent and become less likely to produce heavy precip. in the future.

Compensating Trend (upper): The model projects that the precursor patterns driving heavy precip. will occur more frequently in the future but will become less likely to produce heavy precip.

Compensating Trend (lower): The model projects that the precursor patterns driving heavy precip. will occur less frequently in the future but will become more likely to produce heavy precip.
