"""Point d'entrée VolTotal (gunicorn en production, Flask en local).

En local :  python -m voltotal.wsgi   puis ouvrir http://127.0.0.1:5001
"""
from dotenv import load_dotenv

load_dotenv()

from voltotal.app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5001)
