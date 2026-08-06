import os
import json
import tomllib
from typing import Any, Dict
from src.utils.logger import logger

class ConfigLoader:
    """
    Configuration loader for project config files.
    """
    def __init__(self, config_path: str = "config"):
        self.config_path = config_path
        self.configs: Dict[str, Any] = {}

    def load_config(self, filename: str) -> Dict[str, Any]:
        """
        Loads a configuration file from the config directory.
        """
        path = os.path.join(self.config_path, filename)
        config: Dict[str, Any] = {}
        
        if not os.path.exists(path):
            logger.error(f"Configuration file not found: {path}")
            raise FileNotFoundError(f"Config file {filename} not found at {path}")

        try:
            if filename.endswith(".toml"):
                with open(path, "rb") as f:
                    config = tomllib.load(f)
            elif filename.endswith('.json'):
                with open(path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            else:
                logger.warning(f"Unsupported file format for config: {filename}")
                return {}

            logger.info(f"Successfully loaded configuration: {filename}")
            return config
        
        except Exception as e:
            logger.error(f"Error loading configuration {filename}: {str(e)}")
            raise

    def get_all_configs(self) -> Dict[str, Any]:
        """
        Loads all supported config files in the config directory.
        """
        if not os.path.exists(self.config_path):
            logger.warning(f"Config directory not found: {self.config_path}")
            return {}

        for file in os.listdir(self.config_path):
            if file.endswith(('.toml', '.json')):
                config_name = os.path.splitext(file)[0]
                self.configs[config_name] = self.load_config(file)
        
        return self.configs

# Example singleton instance
config_loader = ConfigLoader()
