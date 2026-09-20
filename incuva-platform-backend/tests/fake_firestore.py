"""Firestore en mémoire pour les tests : pas d'accès réseau, pas de credentials.

Couvre ce que le code de recrutement / tests techniques / messagerie utilise : collections et sous-collections,
where (== et array_contains), limit, order_by (ordre d'insertion), create/set/update/delete, batch, transaction,
et les valeurs spéciales SERVER_TIMESTAMP et Increment.
"""
import copy
import itertools
from datetime import datetime, timezone

from firebase_admin import firestore
from google.api_core.exceptions import AlreadyExists, NotFound
from google.cloud.firestore_v1 import Increment

_ids = itertools.count(1)


def _resolve(new_data, existing=None):
    """Remplace SERVER_TIMESTAMP par une date et Increment par la somme, comme Firestore."""
    existing = existing or {}
    resolved = {}
    for key, value in new_data.items():
        if value is firestore.SERVER_TIMESTAMP:
            resolved[key] = datetime.now(timezone.utc)
        elif isinstance(value, Increment):
            resolved[key] = (existing.get(key) or 0) + value.value
        else:
            resolved[key] = copy.deepcopy(value)
    return resolved


class Snapshot:
    def __init__(self, ref, data):
        self.reference = ref
        self.id = ref.id
        self.exists = data is not None
        self._data = data

    def to_dict(self):
        return copy.deepcopy(self._data) if self._data is not None else None


class DocumentRef:
    def __init__(self, db, path):
        self.db = db
        self.path = path
        self.id = path.rsplit('/', 1)[-1]

    def get(self, transaction=None):
        return Snapshot(self, self.db.data.get(self.path))

    def create(self, data):
        if self.path in self.db.data:
            raise AlreadyExists(f"{self.path} existe déjà")
        self.db.data[self.path] = _resolve(data)

    def set(self, data):
        self.db.data[self.path] = _resolve(data)

    def update(self, data):
        if self.path not in self.db.data:
            raise NotFound(f"{self.path} n'existe pas")
        self.db.data[self.path].update(_resolve(data, self.db.data[self.path]))

    def delete(self):
        self.db.data.pop(self.path, None)

    def collection(self, name):
        return CollectionRef(self.db, f"{self.path}/{name}")


class Query:
    def __init__(self, db, collection_path, filters=(), max_results=None):
        self.db = db
        self.collection_path = collection_path
        self.filters = filters
        self.max_results = max_results

    # --- construction de la requête
    def where(self, field, op, value):
        return Query(self.db, self.collection_path, self.filters + ((field, op, value),), self.max_results)

    def limit(self, count):
        return Query(self.db, self.collection_path, self.filters, count)

    def order_by(self, *args, **kwargs):
        return self  # l'ordre d'insertion suffit pour les tests

    # --- exécution
    def _matches(self, data):
        for field, op, value in self.filters:
            if op == '==' and data.get(field) != value:
                return False
            if op == 'array_contains' and value not in (data.get(field) or []):
                return False
        return True

    def stream(self):
        prefix = self.collection_path + '/'
        results = []
        for path, data in list(self.db.data.items()):
            if path.startswith(prefix) and '/' not in path[len(prefix):] and self._matches(data):
                results.append(Snapshot(DocumentRef(self.db, path), data))
                if self.max_results and len(results) >= self.max_results:
                    break
        return iter(results)

    def get(self):
        return list(self.stream())


class CollectionRef(Query):
    def document(self, doc_id=None):
        return DocumentRef(self.db, f"{self.collection_path}/{doc_id or 'auto%d' % next(_ids)}")

    def add(self, data):
        ref = self.document()
        ref.set(data)
        return None, ref


class Batch:
    def __init__(self):
        self.operations = []

    def update(self, ref, data):
        self.operations.append((ref.update, data))

    def set(self, ref, data):
        self.operations.append((ref.set, data))

    def delete(self, ref):
        self.operations.append((ref.delete, None))

    def commit(self):
        for operation, data in self.operations:
            operation(data) if data is not None else operation()


class Transaction:
    """Écritures immédiates : suffisant pour vérifier la logique (deux soumissions successives)."""

    def set(self, ref, data):
        ref.set(data)

    def update(self, ref, data):
        ref.update(data)

    def delete(self, ref):
        ref.delete()


class FakeFirestore:
    def __init__(self):
        self.data = {}

    def collection(self, name):
        return CollectionRef(self, name)

    def batch(self):
        return Batch()

    def transaction(self):
        return Transaction()

    # --- aides de test
    def put(self, path, data):
        self.data[path] = copy.deepcopy(data)

    def docs(self, collection_path):
        return [snapshot.to_dict() | {'id': snapshot.id} for snapshot in CollectionRef(self, collection_path).stream()]
