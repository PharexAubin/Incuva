import logging
from datetime import datetime, timezone

from firebase_admin import firestore

from .test_results import effective_result

logger = logging.getLogger(__name__)


class QualificationError(Exception):
    """Erreur métier convertie en réponse HTTP par la route (code stable pour le frontend)."""

    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class QualificationService:
    """Champ `qualified` d'une candidature (applications/{id}) : seul point d'écriture.

    - `qualified` (bool, False par défaut ; les anciennes candidatures sans le champ sont lues comme False)
    - `qualified_at` et `qualified_source` ('test' ou 'manual') : trace de la qualification

    Règle commune à toutes les écritures, contrôlée ici à partir de la base (jamais de l'interface) :
    la candidature doit être `accepted`.
    """

    def __init__(self, db):
        self.db = db

    def _change(self, application_id, company_id, updates_if):
        """Lit la candidature dans une transaction, contrôle les règles, puis applique `updates_if(application)`.

        Renvoie True si la candidature a été modifiée, False si elle était déjà dans l'état demandé.
        """
        application_ref = self.db.collection('applications').document(application_id)

        @firestore.transactional
        def run(transaction):
            snapshot = application_ref.get(transaction=transaction)
            if not snapshot.exists:
                raise QualificationError('application_not_found', 'Candidature non trouvée', 404)
            application = snapshot.to_dict()

            if company_id is not None and application.get('company_id') != company_id:
                raise QualificationError('forbidden', 'Cette candidature ne concerne pas votre entreprise', 403)
            if application.get('status') != 'accepted':
                raise QualificationError(
                    'application_not_accepted',
                    "La candidature doit d'abord être acceptée.", 409)

            updates = updates_if(application)
            if updates is None:
                return False
            transaction.update(application_ref, updates)
            return True

        return run(self.db.transaction())

    def qualify(self, application_id, source, company_id=None):
        """Qualifie une candidature acceptée. Idempotent : la date et la source d'origine sont conservées."""
        def updates(application):
            if application.get('qualified'):
                return None
            return {
                'qualified': True,
                'qualified_at': datetime.now(timezone.utc),
                'qualified_source': source,
            }

        return self._change(application_id, company_id, updates)

    def unqualify(self, application_id, company_id):
        """Retire la qualification d'une candidature acceptée. Idempotent."""
        def updates(application):
            if not application.get('qualified'):
                return None
            return {'qualified': False, 'qualified_at': None, 'qualified_source': None}

        return self._change(application_id, company_id, updates)

    def sync_from_attempt(self, attempt, test):
        """Qualification automatique : appelée chaque fois qu'un résultat apparaît ou change
        (soumission, évaluation IA, correction manuelle).

        Qualifie si la tentative est liée à une candidature, si le résultat OFFICIEL est « réussi » et si la
        candidature est toujours acceptée. Ne retire jamais la qualification (c'est un choix de l'entreprise).
        """
        application_id = attempt.get('application_id')
        if not application_id:
            return False

        result = effective_result(attempt, test.get('grading_mode', 'auto'))
        if not (result['official'] and result['passed']):
            return False

        try:
            # company_id du test : la candidature doit appartenir à l'entreprise propriétaire du test
            return self.qualify(application_id, source='test', company_id=test.get('company_id'))
        except QualificationError as error:
            logger.info(f"Pas de qualification automatique pour {application_id} : {error.code}")
            return False
