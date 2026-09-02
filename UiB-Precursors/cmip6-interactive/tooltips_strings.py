
model_dropdown = "  Specify the climate model to use. Data is taken from historical and SSP3.70 scenario runs."

season_dropdown = "  Specify the calendar season."

term_dropdown= """ 
All metrics show change in heavy precipitation occurrence. <br><br>
    <b>  Bias</b>: Difference between historical simulation and ERA5.<br>
    <b>  Change</b>: Predicted change between historical and SSP3.70 simulations, with estimated impact of biases removed. <br>
    <b>  Uncalibrated Change</b>: Predicted change between historical and SSP3.70 simulations, without calibration.
"""
Source_Selection="""
Select which data sources to show in the maps. If multiple sources are selected, they are summed.<br><br>
    <b> Dynamical</b>: Shows the contribution of changes in the frequency of precursor weather patterns. <br>
    <b> Conversion</b>: Shows the contribution of changes in the likelihood of heavy precipitation for a given precursor pattern. <br>
    <b> Non Linear</b>: Shows the contribution of the nonlinear interaction between the conversion and dynamical contributions. <br>"""
colormap_scaler= "Sets the limits for all figures. The units are relative change in heavy precipitation occurrence. For example,as the chance of heavy precipitation is defined as 0.05/day in ERA5, a +20% change indicates a chance of 0.06/day."


Show_Precursor_Maps="  Weather patterns used to isolate dynamical contributions, identified in ERA5 as favouring heavy precipitation. These are specific to each region and season."

Selected_Regions="""  Select one or more regions by clicking on the here. You can select multiple regions with click+shit, click+cmd or click+ctrl.<br><br>
                    <i>Regions were defined algorithmically by grouping locations with shared precipitation variability in ERA5. Names are approximate and no comments on geopolitical borders are intended.</i>"""
Selected_Regions_unique="""  Select one region by clicking on the here.<br><br>
                    <i>Regions were defined algorithmically by grouping locations with shared precipitation variability in ERA5. Names are approximate and no comments on geopolitical borders are intended.</i>"""


group_nonlinear_term = """
  Specifies whether the nonlinear contribution should be added to the conversion or dynamical contribution for classification.
"""

Minimal_difference_thresh = """
  Biases/changes under this threshold will be classed as `minimal'.
"""

sector_slope_thresh = """
  Determines the extent of the Conversion and Dynamical categories. Lower values will lead to more Compounding or Cancelling categorisations.
"""

show_ens = """
  Add metrics computed on individual members to the scatter plot for models with multiple historical and scenario realisations.
"""
diag_interval = "Interval between lines of constant apparent bias or change in the scatter plot, in percentage points"

Minimal_Bias="Model heavy precip. is a close match to reanalysis. \n Both dynamical and conversion biases are small."
Dynamical_Bias_top="The precursor patterns that drive heavy precip. occur too frequently in the model."
Dynamical_Bias_bottom="The precursor patterns that drive heavy precip. occur too rarely in the model."
Conversion_Bias_left="The model is less likely to produce heavy precip. for a given precursor pattern than in reanalysis. "
Conversion_Bias_right="The model is more likely to produce heavy precip. for a given precursor pattern than in reanalysis. "
Compounding_Bias_upper="The precursor patterns that drive heavy precip. occur too frequently and are more likely to produce heavy precip. when they occur than in reanalysis."
Compounding_Bias_lower="The precursor patterns that drive heavy precip. occur too rarely and are less likely to produce heavy precip. when they do occur than in reanalysis."
Compensating_Bias_upper="The precursor patterns that drive heavy precip. occur too frequently but are less likely to produce heavy precip. when they do occur than in reanalysis."
Compensating_Bias_lower="The precursor patterns that drive heavy precip. occur too rarely but are more likely to produce heavy precip. when they do occur than in reanalysis."


Minimal_Trend="The model projects that future heavy precip. will not change substantially."
Dynamical_Trend_top = "The model projects that the precursor patterns that drive heavy precip. will occur more frequently in the future."
Dynamical_Trend_bottom = "The model projects that the precursor patterns that drive heavy precip. will occur less frequently in the future."
Conversion_Trend_left = "The model projects that for the same precursor pattern, heavy precip. will become less likely in the future."
Conversion_Trend_right = "The model projects that for the same precursor pattern, heavy precip. will become more likely in the future."
Compounding_Trend_upper = "The model projects that the precursor patterns driving heavy precip. will become more frequent and become more likely to produce heavy precip. in the future."
Compounding_Trend_lower = "The model projects that the precursor patterns driving heavy precip. will become less frequent and become less likely to produce heavy precip. in the future."
Compensating_Trend_upper = "The model projects that the precursor patterns driving heavy precip. will occur more frequently in the future but will become less likely to produce heavy precip."
Compensating_Trend_lower = "The model projects that the precursor patterns driving heavy precip. will occur less frequently in the future but will become more likely to produce heavy precip."
