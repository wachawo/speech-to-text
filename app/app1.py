#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import logging
import pytz
import urllib3
from flask import Flask, request, jsonify
from flask_cors import CORS
from sqlalchemy.exc import SQLAlchemyError
from models import SessionLocal, engine, Base, Report
from schemas import ReportSchema
from marshmallow import ValidationError

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        pass

load_dotenv('../.env')

LOGGING = {
    'handlers': [logging.StreamHandler()],
    'format': '%(asctime)s.%(msecs)03d [%(levelname)s]: (%(name)s.%(funcName)s) %(message)s',
    'level': logging.INFO,
    'datefmt': '%Y-%m-%d %H:%M:%S',
}
logging.basicConfig(**LOGGING)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TIMEZONE = pytz.timezone("America/New_York")

# создать таблицы при старте (idempotent)
Base.metadata.create_all(bind=engine)

app = Flask(__name__, static_url_path='', static_folder='www')
app.url_map.strict_slashes = False
app.config.from_object(__name__)
app.config['JSON_SORT_KEYS'] = False
CORS(app)

report_post_schema = ReportSchema()
report_get_schema = ReportSchema(many=True)


@app.errorhandler(400)
def bad_request(error):
    return jsonify({"error": "Bad Request", "message": str(error)}), 400

@app.errorhandler(401)
def unauthorized(error):
    return jsonify({"error": "Unauthorized", "message": str(error)}), 401

@app.errorhandler(403)
def forbidden(error):
    return jsonify({"error": "Forbidden", "message": str(error)}), 403

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Not Found", "message": str(error)}), 404

@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({"error": "Method Not Allowed", "message": str(error)}), 405

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal Server Error", "message": str(error)}), 500

@app.errorhandler(ValidationError)
def handle_validation_error(error):
    return jsonify({"error": error.messages}), 400

@app.errorhandler(Exception)
def handle_exception(e):
    # if isinstance(exc, werkzeug.exceptions.NotFound):
    #     return jsonify({'error': 'NotFound'}), 404
    import traceback
    logging.error(f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}")
    response = jsonify({'error': f"{type(e).__name__}: {str(e)}"})
    response.status_code = 500
    return response

@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}, 200

@app.route("/reports", methods=["POST"])
def create_reports():
    if not request.is_json:
        return jsonify(error="Expected JSON body"), 400

    payload = request.get_json(silent=True) or {}

    try:
        data = report_post_schema.load(payload)
    except Exception as e:  # ValidationError — самый частый
        # marshmallow даёт .messages с деталями; но на всякий случай оборачиваем
        messages = getattr(e, "messages", str(e))
        return jsonify(error="Validation error", details=messages), 400

    obj = Report(
        timestamp=data["timestamp"],
        app=data["app"],
        cluster=data["cluster"],
        route=data["route"],
        username=data["username"],
    )
    db = SessionLocal()
    try:
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return jsonify(id=obj.id, status="created"), 201
    except SQLAlchemyError as e:
        db.rollback()
        return jsonify(error="Database error", details=str(e)), 500
    finally:
        db.close()

@app.route("/reports", methods=["GET"])
def list_reports():
    db = SessionLocal()
    try:
        items = (
            db.query(Report)
            .order_by(Report.timestamp.desc())
            .limit(50)
            .all()
        )
        data = report_post_schema.dump(items)
        return jsonify(data), 200
    except SQLAlchemyError as e:
        return jsonify(error="Database error", details=str(e)), 500
    finally:
        db.close()

def main():
    app.run(host="0.0.0.0", port=8000)

if __name__ == '__main__':
    main()
