"""
Reusable paginator utility for FireO queries.
"""
from typing import Dict, List, Any, Optional
from fireo.models import Model


class Paginator:
    """
    Generic paginator for FireO queries.
    """
    
    @staticmethod
    def paginate(query, page: int = 1, per_page: int = 10) -> Dict[str, Any]:
        """
        Paginate a FireO query.
        
        Args:
            query: FireO query object (e.g., from Model.db().filter(...))
            page: Page number (1-indexed)
            per_page: Number of records per page
            
        Returns:
            Dictionary with:
                - 'items': List of items for current page
                - 'total': Total number of items
                - 'page': Current page number
                - 'per_page': Number of items per page
                - 'total_pages': Total number of pages
                - 'has_prev': Boolean indicating if previous page exists
                - 'has_next': Boolean indicating if next page exists
        """
        # Validate page number
        if page < 1:
            page = 1
        
        # Get total count without fetching all records
        total = query.count()
        
        # Fetch only the records needed for current page
        # For page 1: fetch per_page records
        # For page 2+: fetch up to (page * per_page) and slice
        fetch_limit = page * per_page
        all_items = list(query.fetch(fetch_limit))
        
        # Slice to get current page
        skip = (page - 1) * per_page
        items = all_items[skip:skip + per_page]
        
        # Calculate pagination metadata
        total_pages = (total + per_page - 1) // per_page if total > 0 else 1
        has_prev = page > 1
        has_next = page < total_pages
        
        return {
            'items': items,
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': total_pages,
            'has_prev': has_prev,
            'has_next': has_next
        }

