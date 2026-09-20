"""Tests de l'assignation des tests techniques aux candidatures acceptées.

Lancer :  venv/Scripts/python.exe -m unittest tests.test_technical_assignments -v   (depuis incuva-platform-backend)

Les vraies routes sont chargées dans un petit Flask ; Firebase est remplacé par une base en mémoire
(tests/fake_firestore.py) : aucun réseau, aucune clé.
"""
import importlib
import os
import re
import sys
import types
import unittest
from unittest.mock import patch

from firebase_admin import firestore
from flask import Flask, g

sys.path.insert(0, os.path.dirname(__file__))
from fake_firestore import FakeFirestore  # noqa: E402

APP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app')
CURRENT = {}  # base utilisée par la requête en cours (remplacée à chaque test)


def _load_modules():
    """Charge routes.TechnicalTest et routes.messaging sous un package factice, sans passer par app/__init__
    (qui initialise Firebase) : `..firebase.init_firebase` est remplacé par un module portant la fausse base."""
    for name, sub in [('fakeapp', ''), ('fakeapp.routes', 'routes'), ('fakeapp.services', 'services'),
                      ('fakeapp.utils', 'utils'), ('fakeapp.ai', 'ai'), ('fakeapp.firebase', 'firebase')]:
        module = types.ModuleType(name)
        module.__path__ = [os.path.join(APP_DIR, sub)]
        sys.modules[name] = module
    init_firebase = types.ModuleType('fakeapp.firebase.init_firebase')
    init_firebase.db = FakeFirestore()
    sys.modules['fakeapp.firebase.init_firebase'] = init_firebase
    return (importlib.import_module('fakeapp.routes.TechnicalTest'),
            importlib.import_module('fakeapp.routes.messaging'),
            importlib.import_module('fakeapp.services.messaging_service'),
            importlib.import_module('fakeapp.services.test_assignment_service'))


TechnicalTest, messaging_routes, messaging_service_module, assignment_module = _load_modules()

QUESTIONS = [
    {'id': 1, 'type': 'mcq', 'text': 'Q1', 'points': 2, 'multiple_correct': False, 'explanation': 'parce que',
     'options': [{'id': 1, 'text': 'A', 'is_correct': True}, {'id': 2, 'text': 'B', 'is_correct': False}]},
    {'id': 2, 'type': 'true_false', 'text': 'Q2', 'points': 1, 'correct_answer': True, 'explanation': 'x'},
    {'id': 3, 'type': 'open_ended', 'text': 'Q3', 'points': 1, 'expected_keywords': ['react', 'hooks']},
    {'id': 4, 'type': 'coding', 'text': 'Q4', 'points': 1, 'expected_output': '42', 'solution': 'print(42)',
     'test_cases': [{'input': '1', 'expected_output': '42'}]},
]
ANSWERS = [{'question_id': 1, 'selected_options': [1]}, {'question_id': 2, 'answer': True}]


def make_test(**overrides):
    test = {'company_id': 'C1', 'job_id': 'J1', 'title': 'Test React', 'status': 'active', 'questions': QUESTIONS,
            'total_points': 5, 'passing_score': 70, 'is_public': False, 'allow_retake': False, 'show_results': True}
    test.update(overrides)
    return test


def seed(db):
    for uid, data in {
        'C1': {'accountType': 'company', 'companyName': 'Acme'},
        'C2': {'accountType': 'company', 'companyName': 'Autre SA'},
        'U1': {'accountType': 'individual', 'first_name': 'Ada', 'name': 'Lovelace', 'email': 'ada@x.io'},
        'U2': {'accountType': 'individual', 'first_name': 'Bob', 'name': 'Martin', 'email': 'bob@x.io'},
        'U3': {'accountType': 'individual', 'first_name': 'Eve', 'name': 'Durand', 'email': 'eve@x.io'},
    }.items():
        db.put(f'users/{uid}', data)
    db.put('jobs/J1', {'company_id': 'C1', 'title': 'Dev React', 'status': 'active'})
    db.put('jobs/J2', {'company_id': 'C1', 'title': 'Dev Java', 'status': 'active'})
    for app_id, uid, status in [('A1', 'U1', 'accepted'), ('A2', 'U2', 'pending'), ('A3', 'U3', 'rejected')]:
        db.put(f'applications/{app_id}', {'company_id': 'C1', 'candidate_id': uid, 'job_id': 'J1', 'status': status})
    # conversation entreprise <-> U1 pour l'offre J1 (serviceId = job_id) ; U2 et U3 n'en ont pas
    db.put('chats/CH1', {'participants': ['C1', 'U1'], 'serviceId': 'J1', 'lastMessage': '',
                         'unreadCount_C1': 0, 'unreadCount_U1': 0})
    db.put('technical_tests/T1', make_test())
    db.put('technical_tests/T_draft', make_test(status='draft', title='Brouillon'))
    db.put('technical_tests/T_j2', make_test(job_id='J2', title='Autre offre'))
    db.put('technical_tests/T_c2', make_test(company_id='C2', job_id='J3', title="Test d'une autre entreprise"))
    db.put('technical_tests/T_public', make_test(is_public=True, title='Public'))


class BaseCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.flask_app = Flask(__name__)
        cls.flask_app.secret_key = 'test'
        cls.flask_app.register_blueprint(TechnicalTest.technical_test_bp, url_prefix='')
        cls.flask_app.register_blueprint(messaging_routes.messaging_bp)

        @cls.flask_app.before_request
        def load_services():
            g.db = CURRENT['db']
            g.messaging_service = messaging_service_module.MessagingService(CURRENT['db'])

    def setUp(self):
        self.db = FakeFirestore()
        seed(self.db)
        CURRENT['db'] = self.db
        patcher = patch.object(TechnicalTest, 'db', self.db)
        patcher.start()
        self.addCleanup(patcher.stop)
        # transaction simulée : la fonction est simplement appelée avec la fausse transaction
        transactional = patch.object(firestore, 'transactional', lambda fn: (lambda txn: fn(txn)))
        transactional.start()
        self.addCleanup(transactional.stop)
        self.client = self.flask_app.test_client()

    # --- aides
    def login(self, uid, account_type):
        with self.client.session_transaction() as session:
            session['uid'] = uid
            session['account_type'] = account_type

    def logout(self):
        with self.client.session_transaction() as session:
            session.clear()

    def assign(self, application_id='A1', test_id='T1'):
        return self.client.post('/api/technical-tests/assign',
                                json={'application_id': application_id, 'test_id': test_id})

    def submit(self, test_id='T1', answers=ANSWERS):
        return self.client.post(f'/api/technical-tests/{test_id}/submit', json={'answers': answers, 'duration': 3})

    def messages(self, chat_id='CH1'):
        return self.db.docs(f'chats/{chat_id}/messages')

    def assignments(self):
        return self.db.docs('test_assignments')

    def attempts(self):
        return self.db.docs('test_attempts')

    def assign_as_company(self, application_id='A1', test_id='T1'):
        self.login('C1', 'company')
        response = self.assign(application_id, test_id)
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()['data']


class AssignRules(BaseCase):
    """Règles de POST /api/technical-tests/assign : contrôlées côté serveur, pas seulement par l'interface."""

    def test_assign_to_accepted_application_creates_assignment_and_chat_message(self):
        self.login('C1', 'company')
        response = self.assign()
        self.assertEqual(response.status_code, 201)

        assignment = self.assignments()[0]
        self.assertEqual(assignment['id'], 'A1_T1')
        self.assertEqual((assignment['status'], assignment['chat_id'], assignment['candidate_id']),
                         ('assigned', 'CH1', 'U1'))
        self.assertEqual(assignment['test_title'], 'Test React')

        message = self.messages()[0]
        self.assertEqual(message['type'], 'technical_test')
        self.assertEqual(message['assignment_id'], 'A1_T1')
        self.assertEqual(message['content'], '📝 Test technique assigné — Test React')
        self.assertEqual(assignment['message_id'], message['id'])

        chat = self.db.data['chats/CH1']
        self.assertEqual((chat['lastMessageType'], chat['unreadCount_U1']), ('technical_test', 1))

    def test_assign_refused_unless_application_is_accepted(self):
        """Le cas central : pending / rejected / withdrawn sont refusés même par appel direct."""
        self.login('C1', 'company')
        for status in ('pending', 'rejected', 'withdrawn'):
            with self.subTest(status=status):
                self.db.put('applications/A1', {'company_id': 'C1', 'candidate_id': 'U1', 'job_id': 'J1',
                                                'status': status})
                response = self.assign('A1', 'T1')
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.get_json()['code'], 'application_not_accepted')
                self.assertEqual(self.assignments(), [])
                self.assertEqual(self.messages(), [])

    def test_assign_refused_for_another_company(self):
        self.login('C2', 'company')
        response = self.assign()
        self.assertEqual((response.status_code, response.get_json()['code']), (403, 'forbidden'))
        self.assertEqual((self.assignments(), self.messages()), ([], []))

    def test_assign_requires_a_company_session(self):
        self.assertEqual(self.assign().status_code, 403)  # non connecté
        self.login('U1', 'individual')
        self.assertEqual(self.assign().status_code, 403)  # candidat
        self.assertEqual(self.assignments(), [])

    def test_assign_validates_the_test(self):
        self.login('C1', 'company')
        cases = [('T_c2', 403, 'forbidden'),          # test d'une autre entreprise
                 ('T_draft', 409, 'test_inactive'),   # test non actif
                 ('T_j2', 409, 'test_job_mismatch'),  # test d'une autre offre
                 ('inconnu', 404, 'test_not_found')]
        for test_id, status, code in cases:
            with self.subTest(test_id=test_id):
                response = self.assign('A1', test_id)
                self.assertEqual((response.status_code, response.get_json()['code']), (status, code))
        self.assertEqual((self.assignments(), self.messages()), ([], []))

    def test_assign_needs_an_existing_conversation(self):
        self.db.put('applications/A2', {'company_id': 'C1', 'candidate_id': 'U2', 'job_id': 'J1',
                                        'status': 'accepted'})  # U2 n'a pas de conversation
        self.login('C1', 'company')
        response = self.assign('A2', 'T1')
        self.assertEqual((response.status_code, response.get_json()['code']), (409, 'no_conversation'))
        self.assertEqual(self.assignments(), [])

    def test_same_test_cannot_be_assigned_twice(self):
        self.assign_as_company()
        response = self.assign()
        self.assertEqual((response.status_code, response.get_json()['code']), (409, 'already_assigned'))
        self.assertEqual((len(self.assignments()), len(self.messages())), (1, 1))

    def test_assign_needs_both_ids_and_an_existing_application(self):
        self.login('C1', 'company')
        self.assertEqual(self.client.post('/api/technical-tests/assign', json={}).status_code, 400)
        self.assertEqual(self.assign('inconnue', 'T1').status_code, 404)


class CandidateAccess(BaseCase):
    """Le candidat n'accède au test que s'il lui a été assigné, et ne reçoit jamais les réponses."""

    def test_owner_gets_the_full_test(self):
        self.login('C1', 'company')
        test = self.client.get('/api/technical-tests/T1').get_json()['data']
        self.assertTrue(test['questions'][0]['options'][0]['is_correct'])
        self.assertIn('correct_answer', test['questions'][1])

    def test_assigned_candidate_gets_the_test_without_answers(self):
        self.assign_as_company()
        self.login('U1', 'individual')
        response = self.client.get('/api/technical-tests/T1')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['data']['can_submit'])
        questions = {q['id']: q for q in response.get_json()['data']['questions']}
        self.assertNotIn('is_correct', questions[1]['options'][0])
        for hidden in ('explanation', 'correct_answer', 'expected_keywords', 'solution', 'test_cases'):
            for question in questions.values():
                self.assertNotIn(hidden, question)
        # ce que la page candidat affiche reste disponible
        self.assertEqual(questions[4]['expected_output'], '42')
        self.assertIn('multiple_correct', questions[1])
        # le test stocké n'a pas été modifié
        self.assertTrue(self.db.data['technical_tests/T1']['questions'][0]['options'][0]['is_correct'])

    def test_unassigned_candidate_is_refused(self):
        self.login('U2', 'individual')
        response = self.client.get('/api/technical-tests/T1')
        self.assertEqual(response.status_code, 403)

    def test_candidate_loses_access_when_application_is_no_longer_accepted(self):
        self.assign_as_company()
        self.db.data['applications/A1']['status'] = 'rejected'
        self.login('U1', 'individual')
        response = self.client.get('/api/technical-tests/T1')
        self.assertEqual((response.status_code, response.get_json()['code']), (403, 'application_not_accepted'))

    def test_public_test_is_only_a_preview_without_answers(self):
        response = self.client.get('/api/technical-tests/T_public')  # même sans être connecté
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()['data']['can_submit'])  # aperçu : pas de soumission possible
        self.assertNotIn('is_correct', response.get_json()['data']['questions'][0]['options'][0])

    def test_available_tests_are_limited_to_the_assigned_ones(self):
        self.assign_as_company()
        self.login('U1', 'individual')
        tests = self.client.get('/api/jobs/J1/available-tests').get_json()['data']
        self.assertEqual([(t['id'], t['assignment_id']) for t in tests], [('T1', 'A1_T1')])
        self.assertNotIn('is_correct', tests[0]['questions'][0]['options'][0])

        self.login('U2', 'individual')
        self.assertEqual(self.client.get('/api/jobs/J1/available-tests').get_json()['data'], [])

    def test_available_tests_company_side(self):
        self.login('C1', 'company')
        ids = {t['id'] for t in self.client.get('/api/jobs/J1/available-tests').get_json()['data']}
        self.assertEqual(ids, {'T1', 'T_public'})  # actifs de l'offre J1 seulement
        self.login('C2', 'company')
        self.assertEqual(self.client.get('/api/jobs/J1/available-tests').status_code, 403)


class SubmitAccessControl(BaseCase):
    """submit_technical_test : assignation obligatoire, is_public ne suffit pas, une seule tentative."""

    def test_submit_without_assignment_is_refused(self):
        self.login('U1', 'individual')  # candidature acceptée mais test jamais envoyé
        response = self.submit('T1')
        self.assertEqual((response.status_code, response.get_json()['code']), (403, 'not_assigned'))
        self.assertEqual(self.attempts(), [])

    def test_public_flag_does_not_allow_submission(self):
        self.login('U1', 'individual')
        response = self.submit('T_public')
        self.assertEqual((response.status_code, response.get_json()['code']), (403, 'not_assigned'))
        self.assertEqual(self.attempts(), [])

    def test_submit_by_a_candidate_who_is_not_the_assignee(self):
        self.assign_as_company()  # assigné à U1
        self.login('U2', 'individual')
        response = self.submit('T1')
        self.assertEqual((response.status_code, response.get_json()['code']), (403, 'not_assigned'))
        self.assertEqual(self.attempts(), [])

    def test_submit_refused_when_application_no_longer_accepted(self):
        self.assign_as_company()
        self.db.data['applications/A1']['status'] = 'rejected'  # l'entreprise est revenue sur sa décision
        self.login('U1', 'individual')
        response = self.submit('T1')
        self.assertEqual((response.status_code, response.get_json()['code']), (403, 'application_not_accepted'))
        self.assertEqual(self.attempts(), [])

    def test_valid_submission_links_attempt_assignment_and_application(self):
        self.assign_as_company()
        self.login('U1', 'individual')
        response = self.submit('T1')
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['data']['score'], 3)

        attempt = self.attempts()[0]
        self.assertEqual((attempt['assignment_id'], attempt['application_id']), ('A1_T1', 'A1'))
        self.assertEqual((attempt['candidate_name'], attempt['candidate_email']), ('Ada Lovelace', 'ada@x.io'))

        assignment = self.assignments()[0]
        self.assertEqual((assignment['status'], assignment['attempt_id']), ('submitted', attempt['id']))
        self.assertIsNotNone(assignment['submitted_at'])

    def test_second_submission_is_refused_and_creates_no_second_attempt(self):
        self.assign_as_company()
        self.login('U1', 'individual')
        self.assertEqual(self.submit('T1').status_code, 200)
        response = self.submit('T1')
        self.assertEqual((response.status_code, response.get_json()['code']), (409, 'already_submitted'))
        self.assertEqual(len(self.attempts()), 1)

    def test_retake_is_allowed_when_the_test_allows_it(self):
        self.db.put('technical_tests/T1', make_test(allow_retake=True))
        self.assign_as_company()
        self.login('U1', 'individual')
        self.assertEqual(self.submit('T1').status_code, 200)
        self.assertEqual(self.submit('T1').status_code, 200)
        self.assertEqual(len(self.attempts()), 2)

    def test_submit_requires_authentication(self):
        self.assertEqual(self.submit('T1').status_code, 401)


class ResultsAndConversation(BaseCase):
    """Le résultat remonte sur la fiche de candidature ; la conversation expose l'état des tests."""

    def submit_as_candidate(self):
        self.login('U1', 'individual')
        self.assertEqual(self.submit('T1').status_code, 200)

    def test_application_card_shows_the_result(self):
        self.assign_as_company()
        self.login('C1', 'company')
        before = self.client.get('/api/applications/A1/tests').get_json()['data']
        self.assertEqual((before[0]['status'], before[0]['result']), ('assigned', None))

        self.submit_as_candidate()
        self.login('C1', 'company')
        after = self.client.get('/api/applications/A1/tests').get_json()['data'][0]
        self.assertEqual(after['status'], 'submitted')
        self.assertEqual((after['result']['score'], after['result']['max_score']), (3, 5))
        self.assertIn('results', after['attempt'])  # de quoi ouvrir le détail de la tentative

    def test_result_follows_manual_or_ai_grading(self):
        """Le score n'est pas copié dans l'assignation : une correction ultérieure de la tentative apparaît."""
        self.assign_as_company()
        self.submit_as_candidate()
        attempt_id = self.attempts()[0]['id']
        self.db.data[f'test_attempts/{attempt_id}'].update(score=5, percentage=100.0, passed=True)

        self.login('C1', 'company')
        result = self.client.get('/api/applications/A1/tests').get_json()['data'][0]['result']
        self.assertEqual((result['score'], result['percentage'], result['passed']), (5, 100.0, True))

    def test_application_tests_are_private_to_the_owning_company(self):
        self.assign_as_company()
        self.login('C2', 'company')
        self.assertEqual(self.client.get('/api/applications/A1/tests').status_code, 403)
        self.login('U1', 'individual')
        self.assertEqual(self.client.get('/api/applications/A1/tests').status_code, 403)
        self.login('C1', 'company')
        self.assertEqual(self.client.get('/api/applications/inconnue/tests').status_code, 404)

    def test_conversation_exposes_assignments_to_both_participants(self):
        self.assign_as_company()
        for uid, account_type in (('C1', 'company'), ('U1', 'individual')):
            self.login(uid, account_type)
            data = self.client.get('/messaging/conversation/CH1').get_json()
            self.assertTrue(data['success'])
            self.assertEqual([a['id'] for a in data['test_assignments']], ['A1_T1'])
            self.assertEqual(data['messages'][0]['type'], 'technical_test')

    def test_candidate_does_not_see_the_score_when_the_test_hides_results(self):
        self.db.put('technical_tests/T1', make_test(show_results=False))
        self.assign_as_company()
        self.submit_as_candidate()

        self.login('U1', 'individual')
        candidate_view = self.client.get('/messaging/conversation/CH1').get_json()['test_assignments'][0]
        self.assertEqual((candidate_view['status'], candidate_view['result']), ('submitted', None))

        self.login('C1', 'company')
        company_view = self.client.get('/messaging/conversation/CH1').get_json()['test_assignments'][0]
        self.assertEqual(company_view['result']['score'], 3)

    def test_conversation_is_not_available_to_outsiders(self):
        self.assign_as_company()
        self.login('U2', 'individual')
        self.assertEqual(self.client.get('/messaging/conversation/CH1').status_code, 403)

    def test_inbox_shows_the_test_and_the_unread_count(self):
        self.assign_as_company()
        chats = messaging_service_module.MessagingService(self.db).get_chats_for_user('U1')
        self.assertEqual(chats[0]['lastMessage'], '📝 Test technique assigné — Test React')
        self.assertEqual(chats[0]['unreadCount'], 1)


FRONT_SRC = os.path.join(os.path.dirname(os.path.dirname(APP_DIR)), 'incuva-platform-frontend', 'src')


def read_front(*parts):
    path = os.path.join(FRONT_SRC, *parts)
    if not os.path.exists(path):
        raise unittest.SkipTest(f"frontend introuvable : {path}")
    with open(path, encoding='utf-8') as source:
        return source.read()


def technical_test_branch(message_list_source):
    """Le morceau de MessageList.jsx qui affiche la carte du test (de sa condition jusqu'à la branche suivante)."""
    start = message_list_source.find('msg.type === "technical_test"')
    assert start != -1, 'la branche msg.type === "technical_test" a disparu de MessageList.jsx'
    end = message_list_source.find('msg.type === "audio"', start)
    return message_list_source[start:end if end != -1 else None]


class FrontendContract(BaseCase):
    """Contrat entre ce que le backend stocke / renvoie et ce que les composants React lisent.

    Si un champ utilisé par MessageList.jsx / PinnedTestsBar.jsx n'existe pas dans le message ou l'assignation,
    la carte retombe silencieusement sur le texte brut : ces tests rendent cette régression visible.
    """

    def conversation_as(self, uid, account_type):
        self.login(uid, account_type)
        return self.client.get('/messaging/conversation/CH1').get_json()

    def test_stored_message_has_every_field_the_card_reads(self):
        self.assign_as_company()
        stored = self.messages()[0]  # le document réellement écrit dans chats/CH1/messages
        branch = technical_test_branch(read_front('components', 'MessageList.jsx'))

        # la valeur de `type` attendue par le JSX est celle que le backend écrit
        self.assertEqual(stored['type'], 'technical_test')
        # tous les champs `msg.xxx` lus par la carte existent dans le message stocké
        used_fields = set(re.findall(r'\bmsg\.(\w+)', branch))
        self.assertTrue({'type', 'assignment_id', 'test_id', 'test_title'} <= used_fields,
                        f"la carte ne lit plus les champs attendus : {used_fields}")
        self.assertEqual(used_fields - set(stored), set(), "champ lu par la carte mais absent du message stocké")
        # et ils sont renseignés (pas de None/vide qui casserait le lien ou le titre)
        self.assertEqual((stored['assignment_id'], stored['test_id'], stored['test_title']),
                         ('A1_T1', 'T1', 'Test React'))

    def test_card_link_points_to_an_existing_route_with_the_test_id(self):
        branch = technical_test_branch(read_front('components', 'MessageList.jsx'))
        self.assertIn('`/technical-test/${msg.test_id}`', branch)
        self.assertIn('path="/technical-test/:testId"', read_front('App.jsx'))

    def test_card_finds_its_assignment_by_the_message_assignment_id(self):
        self.assign_as_company()
        branch = technical_test_branch(read_front('components', 'MessageList.jsx'))
        self.assertIn('a.id === msg.assignment_id', branch)  # la façon dont le JSX cherche l'assignation

        for uid, account_type in (('U1', 'individual'), ('C1', 'company')):
            with self.subTest(viewer=account_type):
                data = self.conversation_as(uid, account_type)
                message = next(m for m in data['messages'] if m.get('type') == 'technical_test')
                matches = [a for a in data['test_assignments'] if a['id'] == message['assignment_id']]
                self.assertEqual(len(matches), 1, "aucune assignation ne correspond à assignment_id du message")

    def test_assignment_fields_read_by_the_components_exist_in_the_api_payload(self):
        self.assign_as_company()
        branch = technical_test_branch(read_front('components', 'MessageList.jsx'))
        pinned = read_front('components', 'PinnedTestsBar.jsx')
        assignment = self.conversation_as('U1', 'individual')['test_assignments'][0]

        used = set(re.findall(r'\bassignment\??\.(\w+)', branch + pinned)) | {'id'}
        self.assertTrue({'status', 'result', 'test_title', 'test_id'} <= used, used)
        self.assertEqual(used - set(assignment), set(), "champ lu par les composants mais absent de l'API")

    def test_result_fields_read_by_the_components_exist_after_submission(self):
        self.assign_as_company()
        self.login('U1', 'individual')
        self.assertEqual(self.submit('T1').status_code, 200)
        branch = technical_test_branch(read_front('components', 'MessageList.jsx'))
        pinned = read_front('components', 'PinnedTestsBar.jsx')

        result = self.conversation_as('C1', 'company')['test_assignments'][0]['result']
        used = set(re.findall(r'\bresult\??\.(\w+)', branch + pinned))
        self.assertTrue({'score', 'max_score', 'percentage', 'passed'} <= used, used)
        self.assertEqual(used - set(result), set(), "champ de résultat lu par les composants mais absent de l'API")

    def test_role_strings_used_by_the_components_match_the_api(self):
        self.assign_as_company()
        branch = technical_test_branch(read_front('components', 'MessageList.jsx'))
        role_literals = set(re.findall(r'currentAccountType === "(\w+)"', branch + read_front('components', 'PinnedTestsBar.jsx')))
        self.assertEqual(role_literals, {'company'})
        self.assertEqual(self.conversation_as('C1', 'company')['current_account_type'], 'company')
        # côté candidat : tout ce qui n'est pas "company" est traité comme candidat
        self.assertNotEqual(self.conversation_as('U1', 'individual')['current_account_type'], 'company')


class Sanitizing(unittest.TestCase):
    def test_sanitize_does_not_mutate_the_original(self):
        original = make_test()
        cleaned = assignment_module.sanitize_test_for_candidate(original)
        self.assertIn('is_correct', original['questions'][0]['options'][0])
        self.assertNotIn('is_correct', cleaned['questions'][0]['options'][0])


if __name__ == '__main__':
    unittest.main()
