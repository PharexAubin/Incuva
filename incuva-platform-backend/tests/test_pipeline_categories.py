"""Règle des catégories du pipeline (frontend) face aux données réelles du backend.

Lancer :  venv/Scripts/python.exe -m unittest tests.test_pipeline_categories -v   (depuis incuva-platform-backend)

`pipeline.js` est exécuté par Node (fonctions pures, sans React) : on teste le vrai code du frontend, pas une copie.
Les candidatures viennent de la vraie route /jobs/api/job_applications, après de vraies qualifications.
Nécessite Node ; les tests sont ignorés s'il est absent.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from test_technical_assignments import BaseCase, APP_DIR, make_test, FRONT_SRC  # noqa: E402

PIPELINE_JS = os.path.join(FRONT_SRC, 'pages', 'Jobs', 'pipeline.js')
NODE = shutil.which('node')


def run_pipeline(expression, applications=None):
    """Évalue une expression JS avec les exports de pipeline.js et renvoie le résultat (JSON)."""
    if not NODE:
        raise unittest.SkipTest('Node introuvable')
    if not os.path.exists(PIPELINE_JS):
        raise unittest.SkipTest(f'frontend introuvable : {PIPELINE_JS}')
    url = 'file:///' + PIPELINE_JS.replace(os.sep, '/')
    script = (
        f"import * as pipeline from {json.dumps(url)};\n"
        f"const apps = {json.dumps(applications or [])};\n"
        f"const {{ getPipelineCategory, countByCategory, filterByTab, defaultTab, PIPELINE_TABS }} = pipeline;\n"
        f"console.log(JSON.stringify({expression}));"
    )
    done = subprocess.run([NODE, '--input-type=module', '-e', script], capture_output=True, encoding='utf-8', timeout=60)
    if done.returncode != 0:
        raise AssertionError(f'Node a échoué : {done.stderr}')
    return json.loads(done.stdout)


def application(app_id, status, **extra):
    return dict({'application_id': app_id, 'status': status}, **extra)


class PipelineRules(unittest.TestCase):
    def category(self, app):
        return run_pipeline('getPipelineCategory(apps[0])', [app])

    def test_each_status_goes_to_the_expected_category(self):
        cases = [
            (application('a', 'pending'), 'new'),
            (application('a', 'pending', qualified=True), 'new'),        # qualified ne compte que si acceptée
            (application('a', 'accepted'), 'retained'),                   # ancienne candidature, champ absent
            (application('a', 'accepted', qualified=False), 'retained'),
            (application('a', 'accepted', qualified=True), 'qualified'),
            (application('a', 'rejected'), 'refused'),
            (application('a', 'rejected', qualified=True), 'refused'),    # le refus l'emporte
            (application('a', 'withdrawn'), 'refused'),
            (application('a', 'withdrawn', qualified=True), 'refused'),
            (application('a', 'inattendu'), None),
        ]
        for app, expected in cases:
            with self.subTest(status=app['status'], qualified=app.get('qualified')):
                self.assertEqual(self.category(app), expected)

    def test_tabs_are_the_four_categories_then_all(self):
        tabs = run_pipeline('PIPELINE_TABS.map(t => [t.id, t.label])')
        self.assertEqual(tabs, [['new', 'Nouvelles candidatures'], ['retained', 'Candidatures retenues'],
                                ['qualified', 'Qualifiés'], ['refused', 'Refusés / Retirés'], ['all', 'Toutes']])

    def test_counts_add_up_and_all_keeps_unexpected_statuses_visible(self):
        apps = [application('1', 'pending'), application('2', 'pending'), application('3', 'accepted'),
                application('4', 'accepted', qualified=True), application('5', 'rejected'),
                application('6', 'withdrawn'), application('7', 'inattendu')]
        counts = run_pipeline('countByCategory(apps)', apps)
        self.assertEqual(counts, {'new': 2, 'retained': 1, 'qualified': 1, 'refused': 2, 'all': 7})
        # un statut inattendu n'apparaît dans aucun des 4 onglets mais reste visible dans « Toutes »
        self.assertEqual(run_pipeline("filterByTab(apps, 'all').length", apps), 7)

    def test_filtering_returns_only_the_matching_applications(self):
        apps = [application('1', 'pending'), application('2', 'accepted'), application('3', 'accepted', qualified=True),
                application('4', 'rejected')]
        for tab, expected in (('new', ['1']), ('retained', ['2']), ('qualified', ['3']), ('refused', ['4']),
                              ('all', ['1', '2', '3', '4'])):
            with self.subTest(tab=tab):
                ids = run_pipeline(f"filterByTab(apps, {json.dumps(tab)}).map(a => a.application_id)", apps)
                self.assertEqual(ids, expected)

    def test_default_tab_is_the_first_non_empty_one(self):
        for statuses, expected in (([], 'all'), (['rejected'], 'refused'), (['accepted'], 'retained'),
                                   (['pending', 'rejected'], 'new')):
            with self.subTest(statuses=statuses):
                apps = [application(str(i), status) for i, status in enumerate(statuses)]
                self.assertEqual(run_pipeline('defaultTab(countByCategory(apps))', apps), expected)
        only_qualified = [application('1', 'accepted', qualified=True)]
        self.assertEqual(run_pipeline('defaultTab(countByCategory(apps))', only_qualified), 'qualified')


class PipelineWithRealBackendData(BaseCase):
    """La règle du frontend appliquée à ce que le backend renvoie vraiment."""

    def company_applications(self):
        self.login('C1', 'company')
        return self.client.get('/jobs/api/job_applications/J1').get_json()['applications']

    def categories(self):
        apps = self.company_applications()
        result = run_pipeline('apps.map(a => [a.application_id, getPipelineCategory(a)])', apps)
        return dict(result)

    def test_categories_follow_real_qualifications(self):
        # état initial : A1 acceptée (ancienne candidature, sans champ qualified), A2 en attente, A3 refusée
        self.assertEqual(self.categories(), {'A1': 'retained', 'A2': 'new', 'A3': 'refused'})

        self.assertEqual(self.client.post('/jobs/application/A1/qualify').status_code, 200)   # qualification manuelle
        self.assertEqual(self.categories()['A1'], 'qualified')

        self.assertEqual(self.client.post('/jobs/application/A1/unqualify').status_code, 200)
        self.assertEqual(self.categories()['A1'], 'retained')

    def test_a_passed_test_moves_the_candidate_to_qualified(self):
        self.db.put('technical_tests/T1', make_test(passing_score=50))  # 60 % avec les réponses de test
        self.assign_as_company()
        self.login('U1', 'individual')
        self.assertEqual(self.submit('T1').status_code, 200)
        self.assertEqual(self.categories()['A1'], 'qualified')

    def test_a_failed_test_keeps_the_candidate_among_retained(self):
        self.assign_as_company()  # passing_score 70, les réponses donnent 60 %
        self.login('U1', 'individual')
        self.assertEqual(self.submit('T1').status_code, 200)
        self.assertEqual(self.categories()['A1'], 'retained')

    def test_accepting_or_rejecting_moves_the_application_between_tabs(self):
        self.db.data['applications/A2']['status'] = 'accepted'
        self.assertEqual(self.categories()['A2'], 'retained')
        self.db.data['applications/A2']['status'] = 'rejected'
        self.assertEqual(self.categories()['A2'], 'refused')


class QualificationUiContract(BaseCase):
    """Les champs lus par les composants existent dans la réponse de la liste des candidatures."""

    def read(self, *parts):
        path = os.path.join(FRONT_SRC, *parts)
        if not os.path.exists(path):
            raise unittest.SkipTest(f'frontend introuvable : {path}')
        with open(path, encoding='utf-8') as source:
            return source.read()

    def test_fields_read_by_the_pipeline_and_qualification_components_exist_in_the_api(self):
        self.login('C1', 'company')
        self.assertEqual(self.client.post('/jobs/application/A1/qualify').status_code, 200)
        api_application = next(a for a in self.client.get('/jobs/api/job_applications/J1').get_json()['applications']
                               if a['application_id'] == 'A1')

        sources = (self.read('pages', 'Jobs', 'pipeline.js') + self.read('pages', 'Jobs', 'ApplicationQualification.jsx'))
        used = set(re.findall(r'\bapplication\.(\w+)', sources))
        self.assertTrue({'status', 'qualified', 'qualified_source', 'qualified_at', 'application_id'} <= used, used)
        self.assertEqual(used - set(api_application), set(), 'champ lu par le frontend mais absent de l\'API')

    def test_the_qualification_button_is_only_rendered_for_accepted_applications(self):
        component = self.read('pages', 'Jobs', 'ApplicationQualification.jsx')
        self.assertIn('application.status !== "accepted"', component)   # garde d'interface ...
        # ... doublée côté serveur : la route refuse une candidature non acceptée (voir test_qualification.py)
        self.login('C1', 'company')
        self.db.data['applications/A1']['status'] = 'pending'
        self.assertEqual(self.client.post('/jobs/application/A1/qualify').status_code, 409)


if __name__ == '__main__':
    unittest.main()
