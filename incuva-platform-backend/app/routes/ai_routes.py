# backend/app/routes/ai_routes.py
from firebase_admin import firestore
from flask import Blueprint, request, jsonify, current_app, session
import requests
import os
import PyPDF2
import io
from docx import Document
import logging
import json
from botocore.exceptions import BotoCoreError, ClientError

from ..utils.s3_utils import key_from_url, owns_key, download_object

ai_bp = Blueprint('ai', __name__, url_prefix='/api/ai')


def extract_text_from_pdf(data):
    """Extrait le texte d'un PDF (contenu binaire)."""
    pdf_reader = PyPDF2.PdfReader(io.BytesIO(data))
    text = ""
    for page in pdf_reader.pages:
        text += page.extract_text() or ""
    return text[:5000]  # Limiter à 5000 caractères pour éviter des tokens excessifs


def extract_text_from_docx(data):
    """Extrait le texte d'un DOCX (contenu binaire)."""
    doc = Document(io.BytesIO(data))
    text = ""
    for para in doc.paragraphs:
        text += para.text + "\n"
    return text[:5000]


def load_cv_text(cv_url):
    """Télécharge le CV de l'utilisateur connecté depuis S3 et en extrait le texte.

    Renvoie (texte, None, None) ou (None, message d'erreur, code HTTP).
    """
    if 'uid' not in session:
        return None, 'Non authentifié', 401

    key = key_from_url(cv_url)
    if not key or not owns_key(key, session['uid']):
        return None, 'CV introuvable ou accès non autorisé', 403

    ext = key.rsplit('.', 1)[-1].lower()
    if ext == 'doc':
        return None, "Le format .doc n'est pas analysable. Utilisez un PDF ou un DOCX.", 400
    if ext not in ('pdf', 'docx'):
        return None, 'Format de fichier non supporté', 400

    try:
        data = download_object(key)
    except (ClientError, BotoCoreError) as e:
        logging.error(f"Erreur téléchargement CV {key}: {e}")
        return None, 'Impossible de télécharger le CV depuis le stockage', 502

    try:
        text = extract_text_from_pdf(data) if ext == 'pdf' else extract_text_from_docx(data)
    except Exception as e:
        logging.error(f"Erreur lecture CV {key}: {e}")
        return None, 'Le fichier du CV est illisible ou corrompu', 422

    if not text.strip():
        return None, "Aucun texte lisible dans le CV (PDF scanné ou image ?). Utilisez un CV au format texte.", 422
    return text, None, None


# Dans ai_routes.py, améliorez la fonction d'analyse
def analyze_cv_with_ai(cv_text):
    """Utilise l'API HuggingFace pour analyser le CV."""
    try:
        api_key = current_app.config.get('HUGGINGFACE_API_KEY')
        if not api_key:
            raise Exception("Clé API Hugging Face non configurée")

        prompt = f"""
        Analyse ce CV professionnel et extrais les informations suivantes au format JSON:

        CONTEXTE: Tu es un expert en recrutement et en analyse de CV. Ta mission est d'extraire les informations clés pour remplir un profil professionnel.

        CV À ANALYSER:
        {cv_text[:4000]}  # Limite pour éviter les tokens excessifs

        TÂCHES:
        1. Compétences: Liste toutes les compétences techniques (programmation, outils, logiciels) et soft skills (communication, leadership, etc.)
        2. Résumé professionnel: Crée un résumé professionnel de 2-3 phrases basé sur l'expérience et les compétences
        3. Expériences professionnelles: Pour chaque expérience, extrais: poste, entreprise, dates, description concise
        4. Formations: Pour chaque formation, extrais: diplôme/certification, établissement, dates

        FORMAT DE RÉPONSE:
        Réponds UNIQUEMENT avec un JSON valide, sans texte avant ou après:
        {{
            "skills": ["compétence1", "compétence2", "compétence3", ...],
            "summary": "Résumé professionnel de 2-3 phrases",
            "experience": [
                {{
                    "title": "Poste occupé",
                    "company": "Nom de l'entreprise",
                    "start": "Date de début (format: MMM YYYY ou YYYY)",
                    "end": "Date de fin (format: MMM YYYY, YYYY ou 'Present')",
                    "description": "Description concise des responsabilités"
                }}
            ],
            "education": [
                {{
                    "degree": "Diplôme ou certification",
                    "school": "Établissement",
                    "start": "Date de début",
                    "end": "Date de fin"
                }}
            ]
        }}

        RÈGLES:
        - Les compétences doivent être spécifiques et pertinentes
        - Le résumé doit être professionnel et mettre en valeur l'expertise
        - Pour les dates, utiliser le format "Jan 2020" ou "2020-2023" si possible
        - Si une information est manquante, laisser le champ vide
        """

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": "meta-llama/Llama-3.1-8B-Instruct:novita",
            "messages": [
                {
                    "role": "system",
                    "content": "Tu es un expert en analyse de CV et recrutement. Tu extrais les informations des CV avec précision et les formates en JSON."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": 2000,
            "temperature": 0.2,  # Température basse pour plus de cohérence
            "response_format": {"type": "json_object"}
        }

        response = requests.post(
            "https://router.huggingface.co/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=45
        )

        if response.status_code != 200:
            logging.error(f"Erreur API Hugging Face: {response.text}")
            # Fallback: utiliser une extraction simple
            return extract_simple_info(cv_text)

        result = response.json()
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")

        try:
            analysis = json.loads(content)

            # Nettoyer et valider les données
            analysis = clean_ai_analysis(analysis)

            return analysis
        except json.JSONDecodeError:
            logging.error("JSON invalide reçu de l'IA")
            return extract_simple_info(cv_text)

    except requests.Timeout:
        logging.error("Timeout de l'API IA")
        return extract_simple_info(cv_text)
    except Exception as e:
        logging.error(f"Erreur analyse IA: {e}")
        return extract_simple_info(cv_text)


def extract_simple_info(cv_text):
    """Extraction simple en cas d'échec de l'IA."""
    import re

    # Détecter des compétences courantes
    common_skills = [
        'Python', 'JavaScript', 'React', 'Node.js', 'Java', 'C++', 'SQL',
        'HTML', 'CSS', 'TypeScript', 'Vue.js', 'Angular', 'Docker', 'Kubernetes',
        'AWS', 'Azure', 'Git', 'CI/CD', 'Agile', 'Scrum', 'Jira', 'Confluence',
        'Communication', 'Leadership', 'Teamwork', 'Problem Solving', 'Project Management'
    ]

    detected_skills = []
    for skill in common_skills:
        if skill.lower() in cv_text.lower():
            detected_skills.append(skill)

    # Essayer d'extraire les expériences
    experience_patterns = [
        r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}',
        r'\d{4}\s*[-–]\s*(?:Present|\d{4})'
    ]

    experiences = []
    lines = cv_text.split('\n')

    for i, line in enumerate(lines):
        if any(pattern in line for pattern in ['experience', 'expérience', 'work', 'travail']):
            # Prendre les 3 lignes suivantes comme expérience potentielle
            for j in range(1, min(4, len(lines) - i)):
                exp_line = lines[i + j].strip()
                if exp_line and len(exp_line) > 10:
                    experiences.append({"title": exp_line, "company": "", "start": "", "end": "", "description": ""})
                    break

    return {
        "skills": detected_skills[:10],
        "summary": "Profil professionnel extrait automatiquement du CV",
        "experience": experiences[:3],
        "education": []
    }


def clean_ai_analysis(analysis):
    """Nettoie et valide les données de l'analyse IA."""
    cleaned = {
        "skills": [],
        "summary": "",
        "experience": [],
        "education": []
    }

    # Nettoyer les compétences
    if "skills" in analysis and isinstance(analysis["skills"], list):
        skills = analysis["skills"]
        # Éliminer les doublons et normaliser
        seen = set()
        for skill in skills:
            if isinstance(skill, str):
                skill_clean = skill.strip()
                if skill_clean and skill_clean not in seen:
                    seen.add(skill_clean)
                    cleaned["skills"].append(skill_clean)

    # Nettoyer le résumé
    if "summary" in analysis and isinstance(analysis["summary"], str):
        cleaned["summary"] = analysis["summary"].strip()

    # Nettoyer les expériences
    if "experience" in analysis and isinstance(analysis["experience"], list):
        for exp in analysis["experience"]:
            if isinstance(exp, dict):
                cleaned_exp = {
                    "title": exp.get("title", "").strip(),
                    "company": exp.get("company", "").strip(),
                    "start": exp.get("start", exp.get("start_date", "")).strip(),
                    "end": exp.get("end", exp.get("end_date", "")).strip(),
                    "description": exp.get("description", "").strip()
                }
                # Valider que l'expérience a au moins un titre
                if cleaned_exp["title"]:
                    cleaned["experience"].append(cleaned_exp)

    # Nettoyer les formations
    if "education" in analysis and isinstance(analysis["education"], list):
        for edu in analysis["education"]:
            if isinstance(edu, dict):
                cleaned_edu = {
                    "degree": edu.get("degree", "").strip(),
                    "school": edu.get("school", "").strip(),
                    "start": edu.get("start", "").strip(),
                    "end": edu.get("end", "").strip()
                }
                # Valider que la formation a au moins un diplôme
                if cleaned_edu["degree"]:
                    cleaned["education"].append(cleaned_edu)

    return cleaned


@ai_bp.route('/analyze-cv', methods=['POST'])
def analyze_cv():
    """Analyse un CV avec l'IA et extrait les informations."""
    try:
        data = request.get_json()
        cv_url = data.get('cv_url')

        if not cv_url:
            return jsonify({'success': False, 'error': 'URL du CV manquante'}), 400

        cv_text, error, status = load_cv_text(cv_url)
        if error:
            return jsonify({'success': False, 'error': error}), status

        # Analyser avec l'IA
        analysis = analyze_cv_with_ai(cv_text)

        return jsonify({
            'success': True,
            'analysis': analysis
        })

    except Exception as e:
        logging.error(f"Erreur analyse CV: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@ai_bp.route('/map-cv-to-profile', methods=['POST'])
def map_cv_to_profile():
    """Mappe les informations du CV vers le profil utilisateur."""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        cv_analysis = data.get('cv_analysis')

        if not user_id or not cv_analysis:
            return jsonify({'success': False, 'error': 'Données manquantes'}), 400

        # Ici, vous pourriez sauvegarder l'analyse dans la base de données
        # ou mettre à jour directement le profil utilisateur

        return jsonify({
            'success': True,
            'message': 'CV mappé avec succès',
            'mapped_data': cv_analysis
        })

    except Exception as e:
        logging.error(f"Erreur mapping CV: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@ai_bp.route('/auto-complete-profile', methods=['POST'])
def auto_complete_profile():
    """Auto-complète le profil utilisateur à partir du CV."""
    if 'uid' not in session:
        return jsonify({'success': False, 'error': 'Non authentifié'}), 401

    user_id = session['uid']
    data = request.get_json()
    cv_url = data.get('cv_url')

    if not cv_url:
        return jsonify({'success': False, 'error': 'URL du CV manquante'}), 400

    try:
        cv_text, error, status = load_cv_text(cv_url)
        if error:
            return jsonify({'success': False, 'error': error}), status

        # Analyser avec l'IA
        analysis = analyze_cv_with_ai(cv_text)

        # Mettre à jour le profil dans Firestore
        db = firestore.client()
        user_ref = db.collection('users').document(user_id)

        updates = {}

        # Mettre à jour les compétences si elles existent
        if analysis.get('skills'):
            current_skills = user_ref.get().to_dict().get('skills', [])
            new_skills = list(set(current_skills + analysis['skills']))[:20]  # Limiter à 20 compétences
            updates['skills'] = new_skills

        # Mettre à jour la bio si vide
        if analysis.get('summary'):
            current_bio = user_ref.get().to_dict().get('bio', '')
            if not current_bio or len(current_bio) < 50:
                updates['bio'] = analysis['summary']

        # Ajouter les expériences
        if analysis.get('experience'):
            current_experience = user_ref.get().to_dict().get('experience', [])
            # Éviter les doublons
            new_experiences = []
            for exp in analysis['experience']:
                if not any(e.get('title') == exp.get('title') and
                           e.get('company') == exp.get('company')
                           for e in current_experience):
                    new_experiences.append(exp)

            if new_experiences:
                updates['experience'] = current_experience + new_experiences

        # Ajouter les formations
        if analysis.get('education'):
            current_education = user_ref.get().to_dict().get('education', [])
            new_education = []
            for edu in analysis['education']:
                if not any(e.get('degree') == edu.get('degree') and
                           e.get('school') == edu.get('school')
                           for e in current_education):
                    new_education.append(edu)

            if new_education:
                updates['education'] = current_education + new_education

        # Appliquer les mises à jour
        if updates:
            user_ref.update(updates)

        return jsonify({
            'success': True,
            'message': 'Profil auto-complété avec succès',
            'updates_applied': len(updates),
            'analysis': analysis
        })

    except Exception as e:
        logging.error(f"Erreur auto-complétion: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500