# ${PORT:-8080} : Railway fournit normalement PORT ; à défaut on écoute sur
# 8080, le port proposé par défaut lors de la génération du domaine.
web: gunicorn voltotal.wsgi:app --bind 0.0.0.0:${PORT:-8080} --workers 2 --threads 4 --timeout 120
