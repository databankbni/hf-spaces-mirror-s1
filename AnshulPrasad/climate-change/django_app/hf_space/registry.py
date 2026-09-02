from .forms.copernicus import DynamicCDSFormFactory
from .services.copernicus import CopernicusService
from .forms.earth_engine import EarthEngineFormFactory
from .services.earth_engine import EarthEngineService
from .forms.nasa import NASAFormFactory
from .services.nasa import NASAService
from .forms.noaa import NOAAFormFactory
from .services.noaa import NOAAService
from .forms.owid import OWIDFormFactory
from .services.owid import OWIDService
from .forms.world_bank import WorldBankFormFactory
from .services.world_bank import WorldBankService
from .forms.hugging_face import HuggingFaceFormFactory
from .services.hugging_face import HuggingFaceService

PROVIDER_REGISTRY = {
    'copernicus': {
        'name': 'Copernicus Climate Data Store',
        'form_class': DynamicCDSFormFactory.create_form,
        'service_class': CopernicusService,
        'template_name': 'hf_space/dashboards/copernicus.html', # Dedicated template
        'datasets': {
            'reanalysis-era5-single-levels': 'ERA5 Single Levels',
            'reanalysis-era5-pressure-levels': 'ERA5 Pressure Levels',
            'ecv-for-climate-change': 'Essential Climate Variables (1979-Present)'
        }
    },
    'earth_engine': {
        'name': 'Google Earth Engine',
        'form_class': EarthEngineFormFactory.create_form,
        'service_class': EarthEngineService,
        'template_name': 'hf_space/dashboards/earth_engine.html', # Dedicated template
        'datasets': {
            'sentinel-5p': 'Sentinel-5P (Atmospheric Composition)',
            'hansen-global-forest-change': 'Hansen Global Forest Change',
            'modis-land-surface-temp': 'MODIS Land Surface Temperature',
            'jrc-global-surface-water': 'JRC Global Surface Water'
        }
    },
    'nasa': {
        'name': 'NASA Earthdata',
        'form_class': NASAFormFactory.create_form,
        'service_class': NASAService,
        'template_name': 'hf_space/dashboards/nasa.html',
        'datasets': {
            'mur-sst': 'MUR Sea Surface Temperature (JPL)'
        }
    },
    'noaa': {
        'name': 'NOAA Climate Data Online',
        'form_class': NOAAFormFactory.create_form,
        'service_class': NOAAService,
        'template_name': 'hf_space/dashboards/noaa.html',
        'datasets': {
            'cdo-gsom': 'Global Summary of the Month (GSOM)'
        }
    },
    'owid': {
        'name': 'Our World in Data',
        'form_class': OWIDFormFactory.create_form,
        'service_class': OWIDService,
        'template_name': 'hf_space/dashboards/owid.html',
        'datasets': {
            'co2-data': 'Global CO2 Emissions Data'
        }
    },
    'world_bank': {
        'name': 'World Bank Open Data',
        'form_class': WorldBankFormFactory.create_form,
        'service_class': WorldBankService,
        'template_name': 'hf_space/dashboards/world_bank.html',
        'datasets': {
            'wb-climate-data': 'Global Climate & Environmental Indicators'
        }
    },
    'hugging_face': {
        'name': 'Hugging Face Datasets',
        'form_class': HuggingFaceFormFactory.create_form,
        'service_class': HuggingFaceService,
        'template_name': 'hf_space/dashboards/hugging_face.html',
        'datasets': {
            'climate-fever': 'Climate FEVER (Fact-Checking)'
        }
    }
}