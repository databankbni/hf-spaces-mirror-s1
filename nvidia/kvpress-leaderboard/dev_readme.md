### Overview
- The app logic is in `app.py` (run `gradio app.py` to test locally).
- All configurations, including which methods are displayed on landing, displayed names etc are in `settings.py`.


### Adding new results
- Evaluation data is loaded by `load_evaluation_results` in `data.py`. When loading data, the function will try to match the `method_name` (that is the press name in the KVPress library), with a new "pretty" method name. 
- This matching is defined in `METHOD_TO_PRETTY_NAME` in `settings.py`. E.g. `"snapkv" --> "SnapKV"`. Also, add the paper link in the `PRETTY_NAME_TO_PAPER_LINK`.
- (Optional) If you want some hover info to be displayed, you can use `PRETTY_NAME_TO_ADDITIONAL_INFO`. 


### var
- The script in `generate_static_plot.py` can be used to generate a plot like the one on the KVPress README file. 