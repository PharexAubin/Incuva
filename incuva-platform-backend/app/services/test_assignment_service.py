import copy
import logging
from datetime import datetime, timezone

from firebase_admin import firestore
from google.api_core.exceptions import AlreadyExists

from ..utils.recruitment_utils import to_datetime

logger = logging.getLogger(__name__)

# Champs de question qui donnent la solution : jamais envoyés à un candidat
ANSWER_KEYS = (
    'correct_answer', 'explanation', 'expected_keywords', 'expected_approach',
    'evaluation_criteria', 'solution', 'test_cases',
)


class AssignmentError(Exception):
    """Erreur métier convertie en réponse HTTP par la route (code stable pour le frontend)."""

    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _newest_first(assignments):
    floor = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(assignments, key=lambda a: to_datetime(a.get('assigned_at'), default=floor), reverse=True)


def assignment_id_for(application_id, test_id):
    # ID déterministe : un même test ne peut pas être assigné deux fois à la même candidature
    return f"{application_id}_{test_id}"


def sanitize_test_for_candidate(test_data):
    """Copie du test sans les réponses (is_correct des options et champs de ANSWER_KEYS)."""
    test = copy.deepcopy(test_data)
    for question in test.get('questions', []):
        for key in ANSWER_KEYS:
            question.pop(key, None)
        for option in question.get('options', []) or []:
            option.pop('is_correct', None)
    return test


class TestAssignmentService:
    """Assignation d'un test technique à une candidature acceptée, annoncée dans la conversation."""

    __test__ = False  # nom en « Test… » : empêche pytest de le prendre pour une classe de tests

    def __init__(self, db, messaging_service):
        self.db = db
        self.messaging = messaging_service

    # ------------------------------------------------------------------ lecture
    def _to_dict(self, doc):
        data = doc.to_dict()
        data['id'] = doc.id
        return data

    def get(self, assignment_id):
        doc = self.db.collection('test_assignments').document(assignment_id).get()
        return self._to_dict(doc) if doc.exists else None

    def get_for_candidate_and_test(self, candidate_id, test_id):
        docs = list(self.db.collection('test_assignments')
                    .where('test_id', '==', test_id)
                    .where('candidate_id', '==', candidate_id)
                    .limit(1).stream())
        return self._to_dict(docs[0]) if docs else None

    def list_for_application(self, application_id):
        docs = self.db.collection('test_assignments').where('application_id', '==', application_id).stream()
        return _newest_first(self._to_dict(d) for d in docs)

    def list_for_chat(self, chat_id):
        docs = self.db.collection('test_assignments').where('chat_id', '==', chat_id).stream()
        return _newest_first(self._to_dict(d) for d in docs)

    def list_for_candidate_job(self, candidate_id, job_id):
        docs = (self.db.collection('test_assignments')
                .where('candidate_id', '==', candidate_id)
                .where('job_id', '==', job_id).stream())
        return _newest_first(self._to_dict(d) for d in docs)

    def with_results(self, assignments, include_attempt=False, hide_scores_if_not_shown=False):
        """Ajoute à chaque assignation soumise le résultat lu sur la tentative (toujours à jour :
        l'évaluation IA et la correction manuelle modifient la tentative, pas l'assignation).

        hide_scores_if_not_shown : vue candidat, le score n'est donné que si le test a `show_results`.
        """
        tests = {}
        enriched = []
        for assignment in assignments:
            item = dict(assignment)
            item['result'] = None
            attempt_id = assignment.get('attempt_id')
            if assignment.get('status') == 'submitted' and attempt_id:
                attempt_doc = self.db.collection('test_attempts').document(attempt_id).get()
                if attempt_doc.exists:
                    attempt = attempt_doc.to_dict()
                    visible = True
                    if hide_scores_if_not_shown:
                        test_id = assignment['test_id']
                        if test_id not in tests:
                            test_doc = self.db.collection('technical_tests').document(test_id).get()
                            tests[test_id] = test_doc.to_dict() if test_doc.exists else {}
                        visible = tests[test_id].get('show_results', True)
                    if visible:
                        item['result'] = {
                            'attempt_id': attempt_id,
                            'score': attempt.get('score'),
                            'max_score': attempt.get('max_score'),
                            'percentage': attempt.get('percentage'),
                            'passed': attempt.get('passed'),
                            'submitted_at': attempt.get('submitted_at'),
                        }
                        if include_attempt:
                            item['attempt'] = dict(attempt, id=attempt_id)
            enriched.append(item)
        return enriched

    # ------------------------------------------------------------------ assignation
    def assign(self, company_id, application_id, test_id):
        """Assigne un test à une candidature et l'annonce dans la conversation.

        Toutes les règles sont contrôlées ici, à partir des données en base : l'interface peut cacher le
        bouton, mais une requête directe est refusée de la même façon.
        """
        application_doc = self.db.collection('applications').document(application_id).get()
        if not application_doc.exists:
            raise AssignmentError('application_not_found', 'Candidature non trouvée', 404)
        application = application_doc.to_dict()

        if application.get('company_id') != company_id:
            raise AssignmentError('forbidden', 'Cette candidature ne concerne pas votre entreprise', 403)

        if application.get('status') != 'accepted':
            raise AssignmentError(
                'application_not_accepted',
                "Vous devez d'abord accepter la candidature avant d'envoyer un test technique.", 409)

        test_doc = self.db.collection('technical_tests').document(test_id).get()
        if not test_doc.exists:
            raise AssignmentError('test_not_found', 'Test non trouvé', 404)
        test = test_doc.to_dict()

        if test.get('company_id') != company_id:
            raise AssignmentError('forbidden', "Ce test n'appartient pas à votre entreprise", 403)
        if test.get('status') != 'active':
            raise AssignmentError('test_inactive', "Ce test n'est pas actif", 409)
        if test.get('job_id') != application.get('job_id'):
            raise AssignmentError('test_job_mismatch', "Ce test n'est pas rattaché à l'offre de cette candidature", 409)

        candidate_id = application['candidate_id']
        chat_id = self.messaging.get_existing_chat(company_id, candidate_id, application['job_id'])
        if not chat_id:
            raise AssignmentError(
                'no_conversation',
                "Aucune conversation avec ce candidat : contactez-le d'abord.", 409)

        assignment_ref = self.db.collection('test_assignments').document(
            assignment_id_for(application_id, test_id))
        assignment = {
            'application_id': application_id,
            'job_id': application['job_id'],
            'test_id': test_id,
            'test_title': test.get('title', 'Test technique'),
            'company_id': company_id,
            'candidate_id': candidate_id,
            'chat_id': chat_id,
            'status': 'assigned',
            'assigned_at': datetime.now(timezone.utc),
            'submitted_at': None,
            'attempt_id': None,
        }
        try:
            assignment_ref.create(assignment)  # atomique : échoue si l'assignation existe déjà
        except AlreadyExists:
            raise AssignmentError('already_assigned', 'Ce test a déjà été envoyé à ce candidat', 409)

        try:
            message_id = self.messaging.send_test_assignment_message(
                chat_id, company_id, candidate_id,
                {'assignment_id': assignment_ref.id, 'test_id': test_id,
                 'test_title': assignment['test_title'], 'job_id': application['job_id']})
            assignment_ref.update({'message_id': message_id})
        except Exception:
            assignment_ref.delete()  # pas d'assignation sans message dans la conversation
            raise

        assignment.update(id=assignment_ref.id, message_id=message_id)
        return assignment

    # ------------------------------------------------------------------ soumission
    def check_can_submit(self, candidate_id, test_id):
        """Règle d'accès de la soumission : assignation obligatoire (is_public n'y change rien) et
        candidature toujours acceptée. Renvoie l'assignation."""
        assignment = self.get_for_candidate_and_test(candidate_id, test_id)
        if not assignment:
            raise AssignmentError('not_assigned', "Ce test ne vous a pas été envoyé par l'entreprise.", 403)

        application_doc = self.db.collection('applications').document(assignment['application_id']).get()
        application = application_doc.to_dict() if application_doc.exists else {}
        if application.get('candidate_id') != candidate_id or application.get('status') != 'accepted':
            raise AssignmentError(
                'application_not_accepted',
                "Votre candidature n'est plus acceptée : ce test n'est plus accessible.", 403)
        return assignment

    def record_submission(self, assignment, attempt_doc, allow_retake=False):
        """Enregistre la tentative et passe l'assignation à « submitted » dans une même transaction :
        deux soumissions simultanées (double clic, deux onglets) ne créent pas deux tentatives."""
        assignment_ref = self.db.collection('test_assignments').document(assignment['id'])
        attempt_ref = self.db.collection('test_attempts').document()
        attempt_doc = dict(attempt_doc, assignment_id=assignment['id'],
                           application_id=assignment['application_id'])

        @firestore.transactional
        def commit(transaction):
            snapshot = assignment_ref.get(transaction=transaction)
            if not snapshot.exists:
                raise AssignmentError('not_assigned', "Ce test ne vous a pas été envoyé par l'entreprise.", 403)
            if snapshot.to_dict().get('status') == 'submitted' and not allow_retake:
                raise AssignmentError('already_submitted', 'Vous avez déjà passé ce test', 409)
            transaction.set(attempt_ref, attempt_doc)
            transaction.update(assignment_ref, {
                'status': 'submitted',
                'attempt_id': attempt_ref.id,
                'submitted_at': attempt_doc['submitted_at'],
            })

        commit(self.db.transaction())
        return attempt_ref.id
