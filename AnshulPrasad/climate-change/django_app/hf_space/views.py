from django.views import View
from django.shortcuts import render, Http404
from .registry import PROVIDER_REGISTRY

class HomeView(View):
    """Renders the neutral landing page."""

    def get(self, request, *args, **kwargs):
        context = {
            'all_providers': PROVIDER_REGISTRY,
            'active_provider': None,
        }
        return render(request, 'hf_space/home.html', context)


class ProviderDashboardView(View):
    """
    A unified Class-Based View handling dynamic execution for all registered data providers.
    """

    def _get_provider_config(self, provider_id: str) -> dict:
        """Retrieves provider dependencies or raises a 404 exception."""
        config = PROVIDER_REGISTRY.get(provider_id)
        if not config:
            raise Http404(f"Data provider '{provider_id}' is not registered.")
        return config

    def _build_context(self, config: dict, form, provider_id: str, output_data=None) -> dict:
        """Constructs the template context payload."""
        return {
            'form': form,
            'provider_name': config['name'],
            'output_data': output_data,
            'active_provider': provider_id,
            'all_providers': PROVIDER_REGISTRY,
        }

    def get(self, request, provider_id: str, *args, **kwargs):
        """Handles initial page loads (HTTP GET)."""
        config = self._get_provider_config(provider_id)
        FormClass = config['form_class']

        # Extract dataset parameter if the provider supports multiple datasets
        form_kwargs = {}
        dataset_id = None
        if 'datasets' in config:
            dataset_id = request.GET.get('dataset') or list(config['datasets'].keys())[0]
            form_kwargs['dataset_id'] = dataset_id

        form = FormClass(**form_kwargs)
        context = self._build_context(config, form, provider_id)

        if 'datasets' in config:
            context['datasets'] = config['datasets']
            context['current_dataset'] = dataset_id

        return render(request, config['template_name'], context)

    def post(self, request, provider_id: str, *args, **kwargs):
        """Handles form submissions and API execution (HTTP POST)."""
        config = self._get_provider_config(provider_id)
        FormClass = config['form_class']
        ServiceClass = config['service_class']

        form_kwargs = {'data': request.POST}
        dataset_id = None
        if 'datasets' in config:
            dataset_id = request.GET.get('dataset') or list(config['datasets'].keys())[0]
            form_kwargs['dataset_id'] = dataset_id

        form = FormClass(**form_kwargs)
        output_data = None

        if form.is_valid():
            service = ServiceClass()
            # Pass specific dataset_id if applicable; otherwise fallback to provider_id
            target_id = dataset_id if dataset_id else provider_id
            output_data = service.fetch_data(target_id, form.cleaned_data)

        context = self._build_context(config, form, provider_id, output_data)

        if 'datasets' in config:
            context['datasets'] = config['datasets']
            context['current_dataset'] = dataset_id

        return render(request, config['template_name'], context)