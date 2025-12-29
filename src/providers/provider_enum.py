"""
Provider enumeration for BGV Audit system.
All supported providers are defined here.
"""
from enum import Enum


class Provider(str, Enum):
    """Enumeration of all supported BGV providers."""
    DISA_GLOBAL = "Disa Global"
    FIRST_ADVANTAGE = "First Advantage"
    QUEST = "Quest"
    INCHECK = "InCheck"
    SCOUT_LOGIC = "Scout Logic"
    SUMMIT_HEALTH = "Summit Health"
    CITYMD = "CityMD"
    CONCENTRA = "Concentra"
    HEALTHSTREET = "HealthStreet"
    UNIVERSAL = "Universal"
    ESCREEN = "eScreen"
    FASTMED = "FastMed"
    RELIAS = "Relias"
    UNA_HEALTH = "UNA Health"
    
    @classmethod
    def list_all(cls) -> list[str]:
        """Get a list of all provider names."""
        return [provider.value for provider in cls]
    
    @classmethod
    def from_string(cls, value: str) -> 'Provider':
        """Get Provider enum from string value."""
        for provider in cls:
            if provider.value == value:
                return provider
        raise ValueError(f"Unknown provider: {value}")
    
    def __str__(self) -> str:
        """Return the provider name as string."""
        return self.value

