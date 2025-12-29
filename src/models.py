from fireo.models import Model
from fireo.fields import TextField, DateTime, NumberField
from .config import Config

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
