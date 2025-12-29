from typing import TypeVar, Generic, Type, Optional, List, Dict, Any
from fireo.models import Model
from google.cloud import firestore
from src.config import Config

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
        return self.model_class.db().get(doc_id)
    
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
        return self.model_class.db().fetch()
    
    def _get_firestore_client(self):
        """Get Firestore client instance."""
        return firestore.Client()
    
    def _get_collection_ref(self):
        """
        Get the Firestore collection reference with parent path.
        Uses FireO's collection reference which already handles parent paths.
        """
        # Get collection name
        collection_name = getattr(self.model_class.Meta, 'collection_name', None) or self.model_class.collection_name
        
        # Get Firestore client
        db = self._get_firestore_client()
        
        # Construct collection path with parent
        # FireO parent paths are structured as: parent_path/collection_name
        # Config.DB_ROOT_PATH is like "workspaces/bgv-audit"
        # But Firestore needs: collection/document/collection/document
        # So we need to split the parent path and construct properly
        
        # If DB_ROOT_PATH contains slashes, treat as collection/document path
        parent_parts = Config.DB_ROOT_PATH.split('/')
        if len(parent_parts) == 2:
            # Format: "workspaces/bgv-audit" -> collection "workspaces", document "bgv-audit"
            parent_collection = db.collection(parent_parts[0]).document(parent_parts[1])
            return parent_collection.collection(collection_name)
        else:
            # Single part or empty - use as collection name or root
            if Config.DB_ROOT_PATH:
                return db.collection(Config.DB_ROOT_PATH).document('root').collection(collection_name)
            else:
                return db.collection(collection_name)
    
    def _model_to_dict(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert item dictionary to Firestore-compatible format.
        Handles field type conversions if needed.
        """
        result = {}
        for key, value in item.items():
            if key == 'doc_id':
                continue
            # Convert value to Firestore-compatible types
            # FireO models handle this automatically, but for direct Firestore writes we need to be explicit
            if value is None:
                result[key] = None
            elif isinstance(value, (str, int, float, bool)):
                result[key] = value
            elif isinstance(value, dict):
                result[key] = value
            elif isinstance(value, list):
                result[key] = value
            else:
                # For other types, convert to string or handle appropriately
                result[key] = str(value)
        return result
    
    def bulk_create_or_update(self, items: List[Dict[str, Any]], skip_existence_check: bool = False) -> List[T]:
        """
        Bulk create or update multiple documents in Firestore using batch writes.
        This performs a single batch commit, making it much more efficient than individual saves.
        
        Args:
            items: List of dictionaries, each containing:
                - 'doc_id': Document ID (required)
                - Additional key-value pairs for document fields
            skip_existence_check: If True, skips checking if documents exist
                                 (assumes all are new). Default False.
        
        Returns:
            List of created/updated model instances
        
        Example:
            items = [
                {'doc_id': 'doc1', 'field1': 'value1', 'field2': 'value2'},
                {'doc_id': 'doc2', 'field1': 'value3', 'field2': 'value4'},
            ]
            instances = service.bulk_create_or_update(items)
        """
        if not items:
            return []
        
        # Get Firestore client and collection reference
        db = self._get_firestore_client()
        collection_ref = self._get_collection_ref()
        
        # Prepare batch
        batch = db.batch()
        doc_ids = []
        instances_data = {}
        
        # If checking existence, batch fetch existing documents
        existing_docs = {}
        if not skip_existence_check:
            doc_ids_to_check = [item.get('doc_id') for item in items if item.get('doc_id')]
            # Batch get documents
            doc_refs = [collection_ref.document(doc_id) for doc_id in doc_ids_to_check]
            if doc_refs:
                existing_docs_raw = db.get_all(doc_refs)
                for doc in existing_docs_raw:
                    if doc.exists:
                        existing_docs[doc.id] = doc.to_dict()
        
        # Prepare batch operations
        for item in items:
            item_copy = item.copy()
            doc_id = item_copy.pop('doc_id', None)
            if not doc_id:
                continue
            
            doc_ids.append(doc_id)
            doc_ref = collection_ref.document(doc_id)
            
            # Convert to Firestore-compatible dict
            data = self._model_to_dict(item_copy)
            
            # Store data for creating instances later
            instances_data[doc_id] = {
                'data': data,
                'is_update': doc_id in existing_docs
            }
            
            # Add to batch (set with merge=False means full document replacement)
            # For updates, we want to merge with existing data
            if doc_id in existing_docs:
                # Update: merge with existing data
                batch.set(doc_ref, data, merge=True)
            else:
                # Create: set new document
                batch.set(doc_ref, data, merge=False)
        
        # Commit batch (single database call)
        if doc_ids:
            batch.commit()
        
        # Create FireO model instances for return
        instances = []
        for doc_id in doc_ids:
            instance = self.model_class()
            instance.id = doc_id
            data = instances_data[doc_id]['data']
            
            # Set fields on instance
            for key, value in data.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
            
            instances.append(instance)
        
        return instances
    
    def bulk_create(self, items: List[Dict[str, Any]], skip_existence_check: bool = False) -> List[T]:
        """
        Bulk create multiple documents in Firestore using batch writes.
        Raises an error if any document already exists (unless skip_existence_check=True).
        
        Args:
            items: List of dictionaries, each containing:
                - 'doc_id': Document ID (required)
                - Additional key-value pairs for document fields
            skip_existence_check: If True, skips checking if documents exist.
                                 Default False (will raise error if exists).
        
        Returns:
            List of created model instances
        
        Raises:
            ValueError: If a document with the given ID already exists
                        (only if skip_existence_check=False)
        
        Example:
            items = [
                {'doc_id': 'doc1', 'field1': 'value1'},
                {'doc_id': 'doc2', 'field1': 'value2'},
            ]
            instances = service.bulk_create(items)
        """
        if not items:
            return []
        
        # Get Firestore client and collection reference
        db = self._get_firestore_client()
        collection_ref = self._get_collection_ref()
        
        doc_ids = [item.get('doc_id') for item in items if item.get('doc_id')]
        
        if not skip_existence_check:
            # Batch check for existing documents
            doc_refs = [collection_ref.document(doc_id) for doc_id in doc_ids]
            existing_docs = db.get_all(doc_refs)
            existing_ids = [doc.id for doc in existing_docs if doc.exists]
            
            if existing_ids:
                raise ValueError(f"Documents with IDs {existing_ids} already exist. Use bulk_create_or_update() instead.")
        
        # Prepare batch
        batch = db.batch()
        instances_data = {}
        
        # Add all creates to batch
        for item in items:
            item_copy = item.copy()
            doc_id = item_copy.pop('doc_id', None)
            if not doc_id:
                continue
            
            doc_ref = collection_ref.document(doc_id)
            data = self._model_to_dict(item_copy)
            
            instances_data[doc_id] = data
            batch.set(doc_ref, data, merge=False)
        
        # Commit batch (single database call)
        if doc_ids:
            batch.commit()
        
        # Create FireO model instances for return
        instances = []
        for doc_id in doc_ids:
            instance = self.model_class()
            instance.id = doc_id
            data = instances_data[doc_id]
            
            # Set fields on instance
            for key, value in data.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
            
            instances.append(instance)
        
        return instances

