
import os
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

# Determine backend directory and explicitly load .env
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# Import Gemini service
try:
    from gemini_service import analyze_food_packaging, chat_with_wrapshield
except ImportError as exc:
    raise ImportError(
        "Could not import gemini_service.py. "
        "Make sure it is in the same backend folder as app.py."
    ) from exc

# Determine frontend path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")

app = Flask(
    __name__,
    static_folder=FRONTEND_DIR,
    static_url_path=""
)

CORS(app)

# Allowed image extensions
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024


def allowed_file(filename: str) -> bool:
    """Check if the uploaded file has a permitted extension."""
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


@app.route("/")
def serve_index():
    """Serve the frontend if index.html exists."""
    index_path = os.path.join(FRONTEND_DIR, "index.html")

    if os.path.isfile(index_path):
        return send_from_directory(FRONTEND_DIR, "index.html")

    return jsonify({
        "message": "WrapShield AI Backend is running. "
                   "Frontend folder not found."
    })


@app.route("/api/health", methods=["GET"])
def health_check():
    """Check backend and Gemini configuration."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()

    has_api_key = bool(api_key) and api_key != (
        "your_actual_gemini_api_key_here"
    )

    return jsonify({
        "status": "ok",
        "service": "WrapShield AI Backend",
        "gemini_api_configured": has_api_key,
        "mode": "Live Gemini API" if has_api_key
                else "Demo Mode (Mock data fallback)"
    }), 200


@app.route("/api/analyze", methods=["POST"])
def analyze_food():
    """Analyze food packaging using Gemini."""
    try:
        food_name = request.form.get("food_name", "").strip()
        shelf_life = request.form.get("shelf_life", "").strip()
        storage = request.form.get(
            "storage_condition",
            "Ambient room temperature"
        ).strip()
        transport = request.form.get(
            "transport_condition",
            "Standard courier/road transport"
        ).strip()
        budget = request.form.get(
            "budget_priority",
            "Balanced"
        ).strip()

        image_file = request.files.get("image")
        image_bytes = None
        image_mime = None

        # At least a food name or image is required
        if not food_name and (
            not image_file or not image_file.filename
        ):
            return jsonify({
                "error": "Please provide either a food name or "
                         "upload a clear food product image."
            }), 400

        # Validate image
        if image_file and image_file.filename:
            if not allowed_file(image_file.filename):
                return jsonify({
                    "error": "Invalid image format. "
                             "Supported formats: JPG, PNG, WEBP."
                }), 400

            image_bytes = image_file.read()

            if len(image_bytes) > MAX_IMAGE_SIZE_BYTES:
                return jsonify({
                    "error": "Uploaded image exceeds the 5MB limit."
                }), 400

            image_mime = image_file.mimetype or "image/jpeg"

        # Call Gemini service
        result = analyze_food_packaging(
            image_bytes=image_bytes,
            image_mime=image_mime,
            food_name=food_name,
            shelf_life=shelf_life,
            storage=storage,
            transport=transport,
            budget=budget
        )

        return jsonify(result), 200

    except ValueError as exc:
        msg = str(exc)
        status_code = 400 if ("food name" in msg.lower() or "please provide" in msg.lower()) else 502
        return jsonify({
            "error": msg,
            "allow_manual_entry": True
        }), status_code

    except RuntimeError as exc:
        return jsonify({
            "error": str(exc),
            "allow_manual_entry": True
        }), 502

    except Exception as exc:
        app.logger.exception("Unexpected analysis error")
        return jsonify({
            "error": f"An unexpected error occurred: {str(exc)}",
            "allow_manual_entry": True
        }), 500


@app.route("/api/chat", methods=["POST"])
def chat():
    """Chat with the WrapShield AI consultant."""
    try:
        data = request.get_json(silent=True)

        if not isinstance(data, dict):
            return jsonify({
                "error": "Invalid JSON payload."
            }), 400

        new_message = str(data.get("message", "")).strip()

        if not new_message:
            return jsonify({
                "error": "Chat message cannot be empty."
            }), 400

        messages = data.get("messages", [])
        current_food_details = data.get(
            "current_food_details",
            {}
        )

        ai_reply = chat_with_wrapshield(
            messages=messages,
            new_message=new_message,
            current_food_details=current_food_details
        )

        return jsonify({"response": ai_reply}), 200

    except Exception as exc:
        app.logger.exception("Chat processing error")

        return jsonify({
            "error": f"Chat processing failed: {str(exc)}"
        }), 500


if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", "5000"))

    debug = os.getenv(
        "FLASK_DEBUG",
        "True"
    ).lower() in ("true", "1", "yes")

    print("=" * 55)
    print(f"  WrapShield AI Backend running on http://127.0.0.1:{port}")
    print(f"  Frontend available at http://127.0.0.1:{port}/")
    print(f"  Health check: http://127.0.0.1:{port}/api/health")
    print("=" * 55)

    app.run(
        host="0.0.0.0",
        port=port,
        debug=debug
    )