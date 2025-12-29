"""
Helper functions for the BGV Audit application.
"""
import hashlib
from src.providers.base import BaseProvider
from src.providers.enum import Provider


def get_provider_instance(provider_name: str) -> BaseProvider:
    """
    Get provider instance based on provider name using match-case pattern matching.
    
    Args:
        provider_name: Name of the provider from Provider enum
        
    Returns:
        BaseProvider instance
        
    Raises:
        ValueError: If provider class not found or not implemented
    """
    match provider_name:
        case Provider.DISA_GLOBAL.value:
            from src.providers.disa_global import DisaGlobalProvider
            return DisaGlobalProvider()
        
        case Provider.FIRST_ADVANTAGE.value:
            from src.providers.first_advantage import FirstAdvantageProvider
            return FirstAdvantageProvider()
        
        case Provider.QUEST.value:
            from src.providers.quest import QuestProvider
            return QuestProvider()
        
        case Provider.INCHECK.value:
            from src.providers.incheck import InCheckProvider
            return InCheckProvider()
        
        case Provider.SCOUT_LOGIC.value:
            from src.providers.scout_logic import ScoutLogicProvider
            return ScoutLogicProvider()
        
        case Provider.SUMMIT_HEALTH.value:
            from src.providers.summit_health import SummitHealthProvider
            return SummitHealthProvider()
        
        case Provider.CITYMD.value:
            from src.providers.citymd import CityMDProvider
            return CityMDProvider()
        
        case Provider.CONCENTRA.value:
            from src.providers.concentra import ConcentraProvider
            return ConcentraProvider()
        
        case Provider.HEALTHSTREET.value:
            from src.providers.healthstreet import HealthStreetProvider
            return HealthStreetProvider()
        
        case Provider.UNIVERSAL.value:
            from src.providers.universal import UniversalProvider
            return UniversalProvider()
        
        case Provider.ESCREEN.value:
            from src.providers.escreen import EScreenProvider
            return EScreenProvider()
        
        case Provider.FASTMED.value:
            from src.providers.fastmed import FastMedProvider
            return FastMedProvider()
        
        case Provider.RELIAS.value:
            from src.providers.relias import ReliasProvider
            return ReliasProvider()
        
        case Provider.UNA_HEALTH.value:
            from src.providers.una_health import UNAHealthProvider
            return UNAHealthProvider()
        
        case _:
            raise ValueError(f"Provider class not found for: {provider_name}")

def generate_safe_id(raw_string: str) -> str:
    """
    Generate a safe ID for a string.
    
    Args:
        raw_string: The string to generate a safe ID for
        
    Returns:
        A safe ID for the string
    """
    return hashlib.md5(raw_string.encode('utf-8')).hexdigest()


def generate_fingerprint_id(candidate_id: str, service_description: str) -> str:
    """
    Generate a consistent fingerprint ID for a line item.
    This function centralizes the fingerprint generation logic to ensure
    consistency across all parts of the application.
    
    Args:
        candidate_id: Candidate ID
        service_description: Service description
        
    Returns:
        MD5 hash of the fingerprint string (candidate_id|service_description)
    """
    # Normalize inputs
    candidate_id = str(candidate_id).strip()
    service_description = str(service_description).strip()
    
    # Create fingerprint string (same format as ExtractedLineItem.fingerprint())
    fingerprint_str = f"{candidate_id}|{service_description}"
    
    # Generate safe ID using hash
    return generate_safe_id(fingerprint_str)
