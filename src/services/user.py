from src.models import User
from src.services.base import BaseService


class UserService(BaseService[User]):
    """
    Service for user-related operations.
    Inherits generic CRUD operations from BaseService.
    """
    
    def __init__(self):
        """Initialize the UserService with the User model."""
        super().__init__(User)
    
    def create_or_update_user(self, email: str, name: str, profile_pic: str) -> User:
        """
        Create or update a user in Firestore.
        Uses email as the document ID for upsert functionality.
        
        Args:
            email: User's email address (used as document ID)
            name: User's display name
            profile_pic: URL to user's profile picture
            
        Returns:
            User: The created or updated User instance
        """
        return self.create_or_update(
            doc_id=email,
            email=email,
            name=name,
            profile_pic=profile_pic
        )
    
    def get_user_by_email(self, email: str) -> User | None:
        """
        Retrieve a user by their email address.
        
        Args:
            email: User's email address (document ID)
            
        Returns:
            User instance if found, None otherwise
        """
        return self.get_by_id(email)

