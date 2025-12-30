from fireo.models import Model
from fireo.fields import TextField, DateTime, NumberField, ListField, MapField
from .config import Config
from typing import Dict, List, Optional

class BaseModel(Model):
    """
    Base class for all models in this app.
    It automatically sets the Firestore parent path to:
    /<DB_ROOT_PATH>/
    """
    class Meta:
        abstract = True

    @classmethod
    def db(cls):
        """
        Use this for QUERIES.
        Example: User.db().get('email')
        """
        return cls.collection.parent(Config.DB_ROOT_PATH)

    def __init__(self, *args, **kwargs):
        """
        Use this for CREATION.
        Automatically injects the parent path when you create a new instance.
        Example: user = User() -> automatically has parent set.
        """
        if 'parent' not in kwargs:
            kwargs['parent'] = Config.DB_ROOT_PATH
        super().__init__(*args, **kwargs)


class User(BaseModel):
    # We use the email as the Document ID (Key)
    email = TextField(required=True)
    name = TextField()
    profile_pic = TextField()
    last_login = DateTime(auto=True) 

    class Meta:
        collection_name = "users"


class Invoice(BaseModel):
    """
    Invoice metadata model.
    Stores minimal data as per requirements - not the full PDF.
    """
    filename = TextField(required=True)
    invoice_number = TextField(required=True)
    provider_name = TextField(required=True)
    grand_total = NumberField(required=True)
    upload_date = DateTime(auto=True)
    uploaded_by = TextField(required=True)  # User email
    audit_status = TextField()  # "PASS", "FAIL", "PENDING"
    audit_report = MapField()  # JSON summary of audit results
    
    class Meta:
        collection_name = "invoices"


class LineItemFingerprint(BaseModel):
    """
    Stores fingerprints of processed line items for historical duplicate detection.
    Fingerprint = Date + Candidate ID + Name + Amount
    """
    candidate_id = TextField(required=True)
    candidate_name = TextField(required=True)
    service_date = TextField(required=True)  # Stores "Date of Collection" or "Check Date"
    cost = NumberField(required=True)
    
    # Context Fields
    invoice_id = TextField(required=True)
    provider_name = TextField(required=True)
    
    # Optional: Store the extra data as a Map/JSON if needed for debugging
    metadata = MapField() 

    class Meta:
        collection_name = "line_item_fingerprints"

  
