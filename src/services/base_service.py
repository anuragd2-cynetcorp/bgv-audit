from typing import TypeVar, Generic, Type, Optional
from fireo.models import Model

# Type variable for FireO models
T = TypeVar('T', bound=Model)


class BaseService(Generic[T]):
    """
    Base service class providing generic CRUD operations for FireO models.
    
    Subclasses should set the model_class attribute to the specific model they work with.
    """
    
    def __init__(self, model_class: Type[T]):
        """
        Initialize the service with a FireO model class.
        
        Args:
            model_class: The FireO model class this service works with
        """
        self.model_class = model_class
    
    def get_by_id(self, doc_id: str) -> Optional[T]:
        """
        Retrieve a document by its document ID.
        
        Args:
            doc_id: The document ID to retrieve
            
        Returns:
            Model instance if found, None otherwise
        """
        return self.model_class.collection.get(doc_id)
    
    def create(self, doc_id: str, **kwargs) -> T:
        """
        Create a new document in Firestore.
        Raises an error if the document already exists.
        
        Args:
            doc_id: The document ID to use
            **kwargs: Field values to set on the document
            
        Returns:
            The created model instance
            
        Raises:
            ValueError: If a document with the given ID already exists
        """
        # Check if document already exists
        existing = self.get_by_id(doc_id)
        if existing:
            raise ValueError(f"Document with ID '{doc_id}' already exists. Use update() or create_or_update() instead.")
        
        # Create new document with specified ID
        instance = self.model_class()
        instance.id = doc_id
        for key, value in kwargs.items():
            if hasattr(instance, key):
                setattr(instance, key, value)
        
        # Save the document
        instance.save()
        
        return instance
    
    def update(self, doc_id: str, **kwargs) -> T:
        """
        Update an existing document in Firestore.
        Raises an error if the document doesn't exist.
        
        Args:
            doc_id: The document ID to update
            **kwargs: Field values to update on the document
            
        Returns:
            The updated model instance
            
        Raises:
            ValueError: If no document with the given ID exists
        """
        # Get existing document
        instance = self.get_by_id(doc_id)
        if not instance:
            raise ValueError(f"Document with ID '{doc_id}' not found. Use create() or create_or_update() instead.")
        
        # Update fields
        for key, value in kwargs.items():
            if hasattr(instance, key):
                setattr(instance, key, value)
        
        # Save the document
        instance.save()
        
        return instance
    
    def create_or_update(self, doc_id: str, **kwargs) -> T:
        """
        Create or update a document in Firestore (upsert).
        If the document exists, updates it with the provided fields.
        If it doesn't exist, creates a new document with the given ID.
        
        Args:
            doc_id: The document ID to use
            **kwargs: Field values to set on the document
            
        Returns:
            The created or updated model instance
        """
        # Try to get existing document
        instance = self.get_by_id(doc_id)
        
        if instance:
            # Update existing document
            for key, value in kwargs.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
        else:
            # Create new document with specified ID
            instance = self.model_class()
            instance.id = doc_id
            for key, value in kwargs.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
        
        # Save the document (creates or updates in Firestore)
        instance.save()
        
        return instance
    
    def delete(self, doc_id: str) -> bool:
        """
        Delete a document by its document ID.
        
        Args:
            doc_id: The document ID to delete
            
        Returns:
            True if deleted successfully, False if document not found
        """
        instance = self.get_by_id(doc_id)
        if instance:
            instance.delete()
            return True
        return False
    
    def list_all(self) -> list[T]:
        """
        Retrieve all documents from the collection.
        
        Returns:
            List of model instances
        """
        return self.model_class.collection.fetch()

