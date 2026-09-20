from urllib.parse import urlparse, unquote

import boto3
from flask import current_app

# Dossiers S3 dans lesquels un utilisateur dépose ses documents : <dossier>/<uid>/<fichier>
USER_DOCUMENT_FOLDERS = ('cv', 'resumes', 'motivations')

CONTENT_TYPES = {
    'pdf': 'application/pdf',
    'doc': 'application/msword',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}


def content_type_for(filename):
    """Type MIME d'un CV / d'une lettre d'après son extension (None si inconnu)."""
    return CONTENT_TYPES.get(filename.rsplit('.', 1)[-1].lower()) if '.' in filename else None


def get_s3_client():
    return boto3.client(
        's3',
        aws_access_key_id=current_app.config['AWS_ACCESS_KEY_ID'],
        aws_secret_access_key=current_app.config['AWS_SECRET_ACCESS_KEY'],
        region_name=current_app.config['S3_REGION']
    )


def key_from_url(url):
    """Clé S3 d'une URL pointant vers notre bucket, ou None si l'URL est étrangère."""
    if not url:
        return None
    bucket = current_app.config['S3_BUCKET']
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = unquote(parsed.path.lstrip('/'))

    if host.startswith(f"{bucket.lower()}.s3"):  # https://bucket.s3.region.amazonaws.com/cle
        return path or None
    if host.startswith('s3') and path.startswith(f"{bucket}/"):  # https://s3.region.amazonaws.com/bucket/cle
        return path[len(bucket) + 1:] or None
    return None


def owns_key(key, uid):
    """Vrai si la clé se trouve dans l'espace personnel de l'utilisateur."""
    return any(key.startswith(f"{folder}/{uid}/") for folder in USER_DOCUMENT_FOLDERS)


def presigned_get_url(key, expires=600):
    """URL de lecture temporaire : le bucket n'a pas besoin d'être public.

    Le type de contenu est imposé d'après l'extension : les fichiers déposés sans `ContentType`
    (S3 les sert alors en binary/octet-stream) s'affichent quand même dans un iframe.
    """
    params = {'Bucket': current_app.config['S3_BUCKET'], 'Key': key}
    content_type = content_type_for(key)
    if content_type:
        params['ResponseContentType'] = content_type
        if content_type == 'application/pdf':
            params['ResponseContentDisposition'] = 'inline'
    return get_s3_client().generate_presigned_url(
        ClientMethod='get_object',
        Params=params,
        ExpiresIn=expires
    )


def download_object(key):
    """Télécharge un objet du bucket avec les identifiants du serveur."""
    response = get_s3_client().get_object(Bucket=current_app.config['S3_BUCKET'], Key=key)
    return response['Body'].read()
