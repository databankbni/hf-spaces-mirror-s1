from abc import ABC, abstractmethod

class BaseClimateService(ABC):
    @abstractmethod
    def fetch_data(self, config_data:dict) -> dict:
        """
        Executes source-specific API request and parses response.
        Must return a dictionary containing keys: 'stats', 'summary', and 'map_coordinates'.
        """
        pass