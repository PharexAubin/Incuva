"""Tests de la qualification des candidatures (champ `qualified`) et du résultat officiel des tentatives.

Lancer :  venv/Scripts/python.exe -m unittest tests.test_qualification -v   (depuis incuva-platform-backend)

Les corrections passent par les VRAIES routes (évaluation IA, correction manuelle), qui écrivent les champs
ai_* / manual_* de la tentative : on ne simule pas ces champs à la main.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
from test_technical_assignments import (  # noqa: E402
    BaseCase, TechnicalTest, recruitment_module, results_module, make_test,
)

effective_result = results_module.effective_result

ALL_POINTS = {'1': 2, '2': 1, '3': 1, '4': 1}   # total 5/5 = 100 %
NO_POINT = {'1': 0, '2': 0, '3': 0, '4': 0}     # 0 %


class EffectiveResult(unittest.TestCase):
    """Résultat officiel : passed/ai_passed/manual_passed selon la correction (comme TestResultsDashboard)."""

    AUTO = {'score': 3, 'max_score': 5, 'percentage': 60.0, 'passed': False}

    def test_automatic_result_by_default(self):
        result = effective_result(dict(self.AUTO))
        self.assertEqual((result['source'], result['score'], result['percentage'], result['passed'], result['official']),
                         ('auto', 3, 60.0, False, True))

    def test_ai_evaluation_replaces_the_automatic_result(self):
        attempt = dict(self.AUTO, status='evaluated', ai_score=4, ai_percentage=80.0, ai_passed=True)
        result = effective_result(attempt)
        self.assertEqual((result['source'], result['score'], result['percentage'], result['passed']),
                         ('ai', 4, 80.0, True))

    def test_manual_grading_replaces_the_automatic_result(self):
        attempt = dict(self.AUTO, status='manually_graded', manual_score=5, manual_percentage=100.0, manual_passed=True)
        result = effective_result(attempt)
        self.assertEqual((result['source'], result['score'], result['percentage'], result['passed']),
                         ('manual', 5, 100.0, True))

    def test_the_latest_grading_action_wins(self):
        both = dict(self.AUTO, ai_score=4, ai_percentage=80.0, ai_passed=True,
                    manual_score=1, manual_percentage=20.0, manual_passed=False)
        self.assertEqual(effective_result(dict(both, status='manually_graded'))['source'], 'manual')
        self.assertEqual(effective_result(dict(both, status='evaluated'))['source'], 'ai')

    def test_falls_back_to_automatic_when_the_grading_fields_are_missing(self):
        attempt = dict(self.AUTO, status='evaluated', ai_passed=None)
        self.assertEqual(effective_result(attempt)['source'], 'auto')

    def test_manual_grading_mode_only_trusts_the_manual_correction(self):
        ai = dict(self.AUTO, status='evaluated', ai_score=4, ai_percentage=80.0, ai_passed=True)
        manual = dict(self.AUTO, status='manually_graded', manual_score=5, manual_percentage=100.0, manual_passed=True)
        self.assertFalse(effective_result(dict(self.AUTO), 'manual')['official'])
        self.assertFalse(effective_result(ai, 'manual')['official'])
        self.assertTrue(effective_result(manual, 'manual')['official'])
        # en mode auto, tout est officiel
        self.assertTrue(effective_result(ai, 'auto')['official'])


class QualifyRoute(BaseCase):
    """POST /jobs/application/<id>/qualify : la règle « candidature acceptée » est contrôlée côté serveur."""

    def qualify(self, application_id='A1'):
        return self.client.post(f'/jobs/application/{application_id}/qualify')

    def unqualify(self, application_id='A1'):
        return self.client.post(f'/jobs/application/{application_id}/unqualify')

    def application(self, application_id='A1'):
        return self.db.data[f'applications/{application_id}']

    def test_accepted_application_can_be_qualified_manually(self):
        self.login('C1', 'company')
        response = self.qualify()
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.get_json()['qualified'], response.get_json()['changed']), (True, True))
        application = self.application()
        self.assertEqual((application['qualified'], application['qualified_source']), (True, 'manual'))
        self.assertIsNotNone(application['qualified_at'])

    def test_qualify_is_refused_unless_the_application_is_accepted(self):
        """Le cas central : pending / rejected / withdrawn refusés même par appel direct."""
        self.login('C1', 'company')
        for status in ('pending', 'rejected', 'withdrawn'):
            with self.subTest(status=status):
                self.db.data['applications/A1']['status'] = status
                response = self.qualify()
                self.assertEqual((response.status_code, response.get_json()['code']), (409, 'application_not_accepted'))
                self.assertFalse(self.application().get('qualified', False))

    def test_only_the_owning_company_can_qualify(self):
        self.login('C2', 'company')
        response = self.qualify()
        self.assertEqual((response.status_code, response.get_json()['code']), (403, 'forbidden'))
        self.assertFalse(self.application().get('qualified', False))

    def test_qualify_requires_a_company_session_and_an_existing_application(self):
        self.assertEqual(self.qualify().status_code, 403)              # non connecté
        self.login('U1', 'individual')
        self.assertEqual(self.qualify().status_code, 403)              # le candidat ne se qualifie pas lui-même
        self.assertFalse(self.application().get('qualified', False))
        self.login('C1', 'company')
        self.assertEqual(self.qualify('inconnue').status_code, 404)

    def test_qualify_is_idempotent_and_keeps_the_original_source(self):
        self.db.data['applications/A1'].update(qualified=True, qualified_source='test', qualified_at='2026-01-01')
        self.login('C1', 'company')
        response = self.qualify()
        self.assertEqual((response.status_code, response.get_json()['changed']), (200, False))
        self.assertEqual((self.application()['qualified_source'], self.application()['qualified_at']),
                         ('test', '2026-01-01'))

    def test_unqualify_removes_the_qualification(self):
        self.db.data['applications/A1'].update(qualified=True, qualified_source='manual', qualified_at='2026-01-01')
        self.login('C1', 'company')
        response = self.unqualify()
        self.assertEqual((response.status_code, response.get_json()['changed']), (200, True))
        application = self.application()
        self.assertEqual((application['qualified'], application['qualified_at'], application['qualified_source']),
                         (False, None, None))

    def test_unqualify_follows_the_same_server_rule(self):
        self.db.data['applications/A1'].update(qualified=True, qualified_source='manual')
        self.login('C1', 'company')
        for status in ('pending', 'rejected', 'withdrawn'):
            with self.subTest(status=status):
                self.db.data['applications/A1']['status'] = status
                response = self.unqualify()
                self.assertEqual((response.status_code, response.get_json()['code']), (409, 'application_not_accepted'))
                self.assertTrue(self.application()['qualified'])  # inchangée

    def test_unqualify_is_private_to_the_owning_company_and_idempotent(self):
        self.db.data['applications/A1'].update(qualified=True, qualified_source='manual')
        self.login('C2', 'company')
        self.assertEqual(self.unqualify().status_code, 403)
        self.assertTrue(self.application()['qualified'])
        self.logout()
        self.assertEqual(self.unqualify().status_code, 403)
        self.login('C1', 'company')
        self.assertEqual(self.unqualify().get_json()['changed'], True)
        self.assertEqual(self.unqualify().get_json()['changed'], False)  # déjà retirée : pas d'erreur


class AutoQualification(BaseCase):
    """Qualification automatique : le résultat OFFICIEL réussi, sur une candidature acceptée, qualifie."""

    def setUp(self):
        super().setUp()
        self.db.put('technical_tests/T1', make_test(passing_score=50))  # les réponses de test donnent 60 %

    def qualified(self, application_id='A1'):
        return bool(self.db.data[f'applications/{application_id}'].get('qualified'))

    def submit_as_candidate(self):
        self.assign_as_company()
        self.login('U1', 'individual')
        self.assertEqual(self.submit('T1').status_code, 200)
        return self.attempts()[0]['id']

    def grade(self, attempt_id, grades, test_id='T1'):
        self.login('C1', 'company')
        return self.client.post(f'/api/technical-tests/{test_id}/attempts/{attempt_id}/grade',
                                json={'grades': grades, 'feedback': 'ok'})

    def evaluate_with_ai(self, attempt_id, percentage, passed, test_id='T1'):
        self.login('C1', 'company')
        ai_result = {'total_score': percentage / 20, 'percentage': percentage, 'passed': passed}
        with patch.object(TechnicalTest, 'evaluate_with_ai', return_value=ai_result):
            return self.client.post(f'/api/technical-tests/{test_id}/evaluate-ai', json={'attempt_id': attempt_id})

    # --- correction automatique à la soumission
    def test_passing_the_test_qualifies_the_application(self):
        self.submit_as_candidate()
        application = self.db.data['applications/A1']
        self.assertEqual((application['qualified'], application['qualified_source']), (True, 'test'))
        self.assertIsNotNone(application['qualified_at'])

    def test_failing_the_test_does_not_qualify(self):
        self.db.put('technical_tests/T1', make_test(passing_score=70))
        self.submit_as_candidate()
        self.assertFalse(self.qualified())

    # --- évaluation IA
    def test_ai_evaluation_that_passes_qualifies(self):
        self.db.put('technical_tests/T1', make_test(passing_score=70))  # échec automatique
        attempt_id = self.submit_as_candidate()
        self.assertFalse(self.qualified())
        self.assertEqual(self.evaluate_with_ai(attempt_id, 80.0, True).status_code, 200)
        self.assertTrue(self.qualified())

    def test_ai_evaluation_that_fails_does_not_qualify(self):
        self.db.put('technical_tests/T1', make_test(passing_score=70))
        attempt_id = self.submit_as_candidate()
        self.assertEqual(self.evaluate_with_ai(attempt_id, 30.0, False).status_code, 200)
        self.assertFalse(self.qualified())

    # --- correction manuelle
    def test_manual_grading_that_passes_qualifies(self):
        self.db.put('technical_tests/T1', make_test(passing_score=70))
        attempt_id = self.submit_as_candidate()
        self.assertFalse(self.qualified())
        self.assertEqual(self.grade(attempt_id, ALL_POINTS).status_code, 200)
        self.assertTrue(self.qualified())

    def test_manual_grading_that_fails_does_not_qualify(self):
        self.db.put('technical_tests/T1', make_test(passing_score=70))
        attempt_id = self.submit_as_candidate()
        self.assertEqual(self.grade(attempt_id, NO_POINT).status_code, 200)
        self.assertFalse(self.qualified())

    # --- mode de correction manuel : la soumission seule ne qualifie pas
    def test_manual_mode_submission_alone_does_not_qualify(self):
        self.db.put('technical_tests/T1', make_test(passing_score=50, grading_mode='manual'))
        self.submit_as_candidate()  # 60 % en automatique, donc « réussi » si on l'écoutait
        self.assertFalse(self.qualified())

    def test_manual_mode_ai_evaluation_alone_does_not_qualify(self):
        self.db.put('technical_tests/T1', make_test(passing_score=50, grading_mode='manual'))
        attempt_id = self.submit_as_candidate()
        self.assertEqual(self.evaluate_with_ai(attempt_id, 90.0, True).status_code, 200)
        self.assertFalse(self.qualified())

    def test_manual_mode_manual_grading_qualifies(self):
        self.db.put('technical_tests/T1', make_test(passing_score=50, grading_mode='manual'))
        attempt_id = self.submit_as_candidate()
        self.assertEqual(self.grade(attempt_id, ALL_POINTS).status_code, 200)
        self.assertTrue(self.qualified())

    # --- règles de sécurité et de cohérence
    def test_qualification_is_never_removed_automatically(self):
        attempt_id = self.submit_as_candidate()
        self.assertTrue(self.qualified())
        self.assertEqual(self.grade(attempt_id, NO_POINT).status_code, 200)  # note ensuite corrigée à 0 %
        self.assertTrue(self.qualified())

    def test_no_qualification_when_the_application_is_no_longer_accepted(self):
        self.db.put('technical_tests/T1', make_test(passing_score=70))
        attempt_id = self.submit_as_candidate()
        self.db.data['applications/A1']['status'] = 'rejected'  # l'entreprise a refusé entre-temps
        self.assertEqual(self.grade(attempt_id, ALL_POINTS).status_code, 200)
        self.assertFalse(self.qualified())

    def test_second_passing_event_keeps_the_original_qualification_date(self):
        attempt_id = self.submit_as_candidate()
        first = self.db.data['applications/A1']['qualified_at']
        self.assertEqual(self.grade(attempt_id, ALL_POINTS).status_code, 200)
        self.assertEqual(self.db.data['applications/A1']['qualified_at'], first)

    def test_attempt_without_application_link_is_graded_without_error(self):
        """Tentative d'avant l'assignation : pas de application_id, donc rien à qualifier et aucune erreur."""
        self.db.put('test_attempts/legacy', {'test_id': 'T1', 'candidate_id': 'U1', 'score': 5, 'max_score': 5,
                                             'percentage': 100.0, 'passed': True, 'submitted_at': None})
        self.assertEqual(self.grade('legacy', ALL_POINTS).status_code, 200)
        self.assertFalse(self.qualified())

    def test_a_company_cannot_grade_an_attempt_of_another_companys_test(self):
        """Une entreprise ne peut pas faire qualifier une candidature qui n'est pas la sienne en passant
        SON test_id avec la tentative d'un autre test."""
        self.db.put('technical_tests/T1', make_test(passing_score=70))
        attempt_id = self.submit_as_candidate()
        self.login('C2', 'company')
        grade = self.client.post(f'/api/technical-tests/T_c2/attempts/{attempt_id}/grade',
                                 json={'grades': ALL_POINTS, 'feedback': 'x'})
        self.assertEqual(grade.status_code, 404)
        with patch.object(TechnicalTest, 'evaluate_with_ai', return_value={'percentage': 90.0, 'passed': True}):
            ai = self.client.post('/api/technical-tests/T_c2/evaluate-ai', json={'attempt_id': attempt_id})
        self.assertEqual(ai.status_code, 404)
        self.assertFalse(self.qualified())
        self.assertNotIn('manual_passed', self.attempts()[0])  # la tentative n'a pas été modifiée


class OfficialResultDisplay(BaseCase):
    """La fiche de candidature et la carte du chat affichent le résultat officiel (le bug corrigé ici :
    elles ne lisaient que score/percentage/passed et ignoraient ai_* et manual_*)."""

    def setUp(self):
        super().setUp()
        self.db.put('technical_tests/T1', make_test(passing_score=70))

    def submit_as_candidate(self):
        self.assign_as_company()
        self.login('U1', 'individual')
        self.assertEqual(self.submit('T1').status_code, 200)
        return self.attempts()[0]['id']

    def application_result(self):
        self.login('C1', 'company')
        return self.client.get('/api/applications/A1/tests').get_json()['data'][0]['result']

    def candidate_chat_result(self):
        self.login('U1', 'individual')
        return self.client.get('/messaging/conversation/CH1').get_json()['test_assignments'][0]['result']

    def grade_manually(self, attempt_id, grades):
        self.login('C1', 'company')
        return self.client.post(f'/api/technical-tests/T1/attempts/{attempt_id}/grade',
                                json={'grades': grades, 'feedback': 'ok'})

    def test_automatic_result_before_any_correction(self):
        self.submit_as_candidate()
        result = self.application_result()
        self.assertEqual((result['source'], result['score'], result['percentage'], result['passed']),
                         ('auto', 3, 60.0, False))

    def test_manual_grading_is_reflected_on_the_application_card_and_the_chat(self):
        attempt_id = self.submit_as_candidate()
        self.assertEqual(self.grade_manually(attempt_id, ALL_POINTS).status_code, 200)
        # la route a réellement écrit manual_* et laissé passed/percentage à leur valeur automatique
        attempt = self.attempts()[0]
        self.assertEqual((attempt['manual_passed'], attempt['status'], attempt['passed']), (True, 'manually_graded', False))

        for name, result in (('fiche', self.application_result()), ('chat candidat', self.candidate_chat_result())):
            with self.subTest(vue=name):
                self.assertEqual((result['source'], result['passed'], result['percentage'], result['score']),
                                 ('manual', True, 100.0, 5))

    def test_ai_evaluation_is_reflected_on_the_application_card(self):
        attempt_id = self.submit_as_candidate()
        self.login('C1', 'company')
        with patch.object(TechnicalTest, 'evaluate_with_ai',
                          return_value={'total_score': 4.0, 'percentage': 80.0, 'passed': True}):
            self.assertEqual(self.client.post('/api/technical-tests/T1/evaluate-ai',
                                              json={'attempt_id': attempt_id}).status_code, 200)
        result = self.application_result()
        self.assertEqual((result['source'], result['passed'], result['percentage']), ('ai', True, 80.0))

    def test_manual_mode_shows_no_grade_until_the_manual_correction(self):
        self.db.put('technical_tests/T1', make_test(passing_score=50, grading_mode='manual'))
        attempt_id = self.submit_as_candidate()

        waiting = self.application_result()
        self.assertTrue(waiting['awaiting_grading'])
        self.assertEqual((waiting['score'], waiting['percentage'], waiting['passed']), (None, None, None))
        self.assertTrue(self.candidate_chat_result()['awaiting_grading'])

        self.assertEqual(self.grade_manually(attempt_id, ALL_POINTS).status_code, 200)
        graded = self.application_result()
        self.assertFalse(graded['awaiting_grading'])
        self.assertEqual((graded['source'], graded['passed'], graded['percentage']), ('manual', True, 100.0))

    def test_candidate_still_does_not_see_the_score_when_the_test_hides_results(self):
        self.db.put('technical_tests/T1', make_test(passing_score=70, show_results=False))
        attempt_id = self.submit_as_candidate()
        self.assertEqual(self.grade_manually(attempt_id, ALL_POINTS).status_code, 200)
        self.assertIsNone(self.candidate_chat_result())
        self.assertEqual(self.application_result()['passed'], True)  # l'entreprise, elle, voit


class QualifiedField(BaseCase):
    """Valeur par défaut du champ et non-exposition au candidat."""

    def test_new_applications_start_unqualified(self):
        created = recruitment_module.RecruitmentService(self.db).create_application(
            'U2', 'J1', resume_url='https://x/cv.pdf', motivation='', skills='', experience='', phone='')
        self.assertIs(self.db.data[f'applications/{created}']['qualified'], False)

    def test_quick_apply_starts_unqualified(self):
        self.db.put('users/U4', {'accountType': 'individual', 'first_name': 'Dan', 'name': 'Petit', 'email': 'd@x.io',
                                 'phone': '06', 'bio': 'bio', 'skills': ['react'], 'cvUrl': 'https://x/cv.pdf'})
        self.login('U4', 'individual')
        response = self.client.post('/jobs/quick-apply/J1')
        self.assertEqual(response.status_code, 200, response.get_json())
        created = self.db.data[f"applications/{response.get_json()['application_id']}"]
        self.assertIs(created['qualified'], False)

    def test_company_list_exposes_qualified_with_a_default_for_old_applications(self):
        self.db.data['applications/A2'].update(qualified=True, qualified_source='manual')
        self.login('C1', 'company')
        applications = {a['application_id']: a for a in
                        self.client.get('/jobs/api/job_applications/J1').get_json()['applications']}
        self.assertIs(applications['A1']['qualified'], False)   # ancienne candidature, champ absent en base
        self.assertNotIn('qualified', self.db.data['applications/A1'])
        self.assertIs(applications['A2']['qualified'], True)

    def test_candidate_never_sees_the_qualification(self):
        self.db.data['applications/A1'].update(qualified=True, qualified_source='test', qualified_at='2026-01-01')
        self.login('U1', 'individual')
        mine = self.client.get('/jobs/api/my_applications').get_json()['applications']
        self.assertEqual(len(mine), 1)
        for internal_field in ('qualified', 'qualified_at', 'qualified_source'):
            self.assertNotIn(internal_field, mine[0])

        for application in recruitment_module.RecruitmentService(self.db).get_user_applications('U1'):
            for internal_field in ('qualified', 'qualified_at', 'qualified_source'):
                self.assertNotIn(internal_field, application)


if __name__ == '__main__':
    unittest.main()
