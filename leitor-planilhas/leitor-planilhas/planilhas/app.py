# ajuste de rotas
from flask import Flask
from flask_cors import CORS
from routes.planilha_routes import planilha_routes
from routes.usuario_routes import usuario_routes

def create_app():
    app = Flask(__name__)
    CORS(app)

    # Registro das rotas
    app.register_blueprint(planilha_routes, url_prefix='/planilhas')
    app.register_blueprint(usuario_routes, url_prefix='/usuarios')

    return app


app = create_app()

