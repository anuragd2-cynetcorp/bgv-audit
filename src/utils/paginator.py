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
        
        # 2. Calculate Offset
        offset = (page - 1) * per_page
        
        # 3. Fetch only the needed page using native Firestore offset
        # This is much better than slicing a list in Python, but still costs reads.
        items = list(query.offset(offset).limit(per_page).fetch())
        
        total_pages = (total + per_page - 1) // per_page if total > 0 else 1
        
        return {
            'items': items,
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': total_pages,
            'has_next': page < total_pages,
            'has_prev': page > 1
        }