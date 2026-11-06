from terp.core import BaseService

from .models import Doc


class DocService(BaseService):
    model = Doc
