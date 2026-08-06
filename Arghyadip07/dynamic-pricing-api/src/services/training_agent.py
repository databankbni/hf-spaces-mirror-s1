"""
Background agent that continuously trains the demand model to learn from newly ingested data.
"""

import logging
import threading
import time

from src.models.demand import train_and_save_model_artifact
from src.services.pricing_service import PricingService
from src.services.rl_pricing_service import RLPricingService

logger = logging.getLogger(__name__)


class TrainingAgent:
    """
    Background agent that periodically retrains the demand model and reloads
    it into the live pricing services without requiring a restart.
    """

    def __init__(
        self,
        pricing_service: PricingService,
        rl_pricing_service: RLPricingService,
        interval_seconds: float = 3600.0,
    ):
        self.pricing_service = pricing_service
        self.rl_pricing_service = rl_pricing_service
        self.interval_seconds = interval_seconds

        self._running: bool = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the continuous training loop in a daemon thread."""
        if self._running:
            logger.warning("TrainingAgent is already running.")
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info(f"✓ TrainingAgent started (interval={self.interval_seconds}s)")

    def stop(self) -> None:
        """Gracefully stop the agent."""
        if not self._running:
            return
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("✓ TrainingAgent stopped.")

    def _run_loop(self) -> None:
        """The main loop for periodic model training."""
        logger.info("TrainingAgent loop started.")
        while self._running:
            # We sleep in small chunks so that stop() can interrupt quickly
            for _ in range(int(self.interval_seconds)):
                if not self._running:
                    break
                time.sleep(1.0)
            
            if not self._running:
                break
            
            logger.info("TrainingAgent initiating demand model retraining...")
            try:
                # 1. Train and save the new model artifact
                model, reference_row, metrics = train_and_save_model_artifact()
                
                # 2. Hot-reload the models into the live services
                self.pricing_service.reload_model(model, reference_row)
                self.rl_pricing_service.reload_model(model, reference_row)
                
                logger.info(
                    f"✓ Demand model retrained successfully! "
                    f"(RMSE: {metrics.get('rmse', 0):.4f}, "
                    f"Train/Test split: {metrics.get('n_train')}/{metrics.get('n_test')})"
                )
            except Exception as exc:
                logger.error(f"TrainingAgent failed to retrain model: {exc}", exc_info=True)
        
        logger.info("TrainingAgent loop exited.")
