"""Résultat « officiel » d'une tentative de test technique.

Selon la façon dont la tentative a été corrigée, le résultat ne se trouve pas dans les mêmes champs :

| Situation                                      | Champs qui font foi                          |
|------------------------------------------------|----------------------------------------------|
| correction automatique (à la soumission)       | passed / percentage / score                  |
| évaluation IA (status == 'evaluated')          | ai_passed / ai_percentage / ai_score         |
| correction manuelle (status == 'manually_graded') | manual_passed / manual_percentage / manual_score |

C'est la priorité déjà appliquée par TestResultsDashboard.jsx (la dernière action de correction l'emporte).
Cette fonction unique sert à l'affichage (fiche de candidature, carte du chat) ET à la qualification
automatique : les deux ne peuvent donc pas se contredire.
"""


def effective_result(attempt, grading_mode='auto'):
    """Résultat officiel d'une tentative.

    Dans un test en `grading_mode == 'manual'`, seule la correction manuelle est officielle : le score
    automatique calculé à la soumission n'est pas le résultat retenu (`official` vaut alors False).
    """
    status = attempt.get('status')

    if status == 'manually_graded' and attempt.get('manual_passed') is not None:
        source, score = 'manual', attempt.get('manual_score')
        percentage, passed = attempt.get('manual_percentage'), attempt.get('manual_passed')
    elif status == 'evaluated' and attempt.get('ai_passed') is not None:
        source, score = 'ai', attempt.get('ai_score')
        percentage, passed = attempt.get('ai_percentage'), attempt.get('ai_passed')
    else:
        source, score = 'auto', attempt.get('score')
        percentage, passed = attempt.get('percentage'), attempt.get('passed')

    if percentage is None:
        percentage = attempt.get('percentage')
    official = (source == 'manual') if grading_mode == 'manual' else True

    return {
        'source': source,
        'score': score,
        'max_score': attempt.get('max_score'),
        'percentage': percentage,
        'passed': bool(passed),
        'official': official,
    }
