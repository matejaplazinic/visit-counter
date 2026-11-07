"""Run a WSGI server on the port supplied through the environment."""

from waitress import serve

from app import create_app

if __name__ == "__main__":
    application = create_app()
    serve(application, host="0.0.0.0", port=application.config["APP_PORT"])
