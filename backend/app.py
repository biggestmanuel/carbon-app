from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from dotenv import load_dotenv

# Load variables from .env into the environment before Config reads them
load_dotenv()

app = Flask(__name__)
app.config.from_object("config.Config")

db = SQLAlchemy(app)
jwt = JWTManager(app)

# Allow the React dev server (default localhost:3000) to call this API.
# Adjust origins for production before deploying.
CORS(app, resources={r"/*": {"origins": ["http://localhost:3000"]}})

# Import routes
from routes.auth import auth_bp
from routes.footprint import footprint_bp

app.register_blueprint(auth_bp, url_prefix="/auth")
app.register_blueprint(footprint_bp, url_prefix="/footprint")

# Create tables on first run if they don't exist yet
with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True)
