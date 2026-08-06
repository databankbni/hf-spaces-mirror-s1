from dataclasses import dataclass, field

from src.experiments.ab_testing import ABTestManager
from src.models.causal_uplift import CausalUpliftModel
from src.services.benchmark_service import BenchmarkService
from src.services.competitor_service import CompetitorSignalService
from src.services.elasticity_service import ElasticityService
from src.services.inventory_service import InventoryOptimizationService
from src.services.analytics_service import AnalyticsService
from src.services.multi_product_service import MultiProductService
from src.services.monitoring_service import MonitoringService
from src.services.pricing_agent import PricingAgent
from src.services.pricing_service import PricingService
from src.services.rl_pricing_service import RLPricingService
from src.services.validation_service import ValidationService
from src.services.training_agent import TrainingAgent


@dataclass
class ApiRuntime:
    pricing_service: PricingService = field(default_factory=PricingService)
    elasticity_service: ElasticityService = field(default_factory=ElasticityService)
    rl_pricing_service: RLPricingService = field(default_factory=RLPricingService)
    multi_product_service: MultiProductService = field(default_factory=MultiProductService)
    inventory_service: InventoryOptimizationService = field(default_factory=InventoryOptimizationService)
    analytics_service: AnalyticsService = field(default_factory=AnalyticsService)
    competitor_service: CompetitorSignalService = field(default_factory=CompetitorSignalService)
    monitoring_service: MonitoringService = field(default_factory=MonitoringService)
    ab_test_manager: ABTestManager = field(default_factory=ABTestManager)
    causal_uplift_model: CausalUpliftModel = field(default_factory=CausalUpliftModel)
    validation_service: ValidationService = field(default_factory=ValidationService)
    benchmark_service: BenchmarkService = field(init=False)
    pricing_agent: PricingAgent = field(init=False)
    training_agent: TrainingAgent = field(init=False)

    def __post_init__(self) -> None:
        self.benchmark_service = BenchmarkService(
            pricing_service=self.pricing_service,
            rl_pricing_service=self.rl_pricing_service,
        )
        self.pricing_agent = PricingAgent(
            pricing_service=self.pricing_service,
            rl_pricing_service=self.rl_pricing_service,
            interval_seconds=30.0,
            product_id=1,
            default_unit_cost=60.0,
        )
        self.training_agent = TrainingAgent(
            pricing_service=self.pricing_service,
            rl_pricing_service=self.rl_pricing_service,
            interval_seconds=3600.0,
        )

    def startup(self) -> None:
        self.pricing_service.startup()
        self.elasticity_service.startup()
        self.rl_pricing_service.startup()
        self.analytics_service.startup()
        self.validation_service.startup()
        self.pricing_agent.start()
        self.training_agent.start()

    def shutdown(self) -> None:
        self.training_agent.stop()
        self.pricing_agent.stop()
        self.analytics_service.shutdown()


runtime = ApiRuntime()
