import os
import sys
import time
import json
import re
import base64
import traceback
import requests
from dotenv import load_dotenv

# Ensure .env is explicitly loaded from the backend directory
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BACKEND_DIR, ".env")
load_dotenv(dotenv_path=ENV_PATH)

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Prioritized list of Gemini models for automatic failover during high demand / rate limits
PRIMARY_MODELS_POOL = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash-8b",
    "gemini-flash-latest",
    "gemini-1.5-pro",
    "gemini-pro-latest"
]


def get_candidate_models() -> list:
    """
    Returns an ordered, deduplicated list of candidate Gemini models,
    prioritizing the configured GEMINI_MODEL / DEFAULT_MODEL first.
    """
    env_model = os.getenv("GEMINI_MODEL", "").strip()
    active_default = env_model if env_model else DEFAULT_MODEL

    candidates = [active_default] + PRIMARY_MODELS_POOL
    seen = set()
    ordered = []
    for model in candidates:
        if model and model not in seen:
            seen.add(model)
            ordered.append(model)
    return ordered


SYSTEM_INSTRUCTION = """You are WrapShield AI, a friendly packaging advisor helping farmers, home food makers, and small food businesses choose the right packaging.

LANGUAGE & AUDIENCE GUIDELINES:
- Your audience includes rural farmers, home bakers, and small vendors who do NOT know complex plastic chemical names or acronyms (like BOPP, LLDPE, EVOH, WVTR, OTR).
- Always use plain, simple, everyday English that anyone can understand.
- When naming materials, describe what the packet actually looks like in real life first, with common trade names in parentheses so they can ask packaging suppliers for it.
  Example: "Brown Paper Pouch with Silver Foil Lining & Air Valve (Kraft + Met-PET laminate)" or "Shiny Silver Foil Snack Pouch (like a chips packet)".

OBJECTIVES:
1. Examine the food product image carefully when provided:
   - Identify the food accurately in Title Case (e.g., "Potato Chips", "Roasted Coffee Beans", "Roasted Peanuts", "Fresh Bread").
   - If the food is potato chips or crisps, specifically name it "Potato Chips".
   - If the image is unclear or cannot be identified, you MUST set 'identified_food' to:
     "Food could not be identified confidently. Please enter the food name manually."
     and set 'confidence' to "Low".
2. If no image is provided, use the user's manually entered food name.
3. In 'recommended_material', give a simple, visual description of the best packet.
4. In 'packaging_structure', explain the layers simply from outside to inside:
   Example: "Outside: Tough paper or clear film for strength; Middle: Silver foil layer to block air, water, and sun; Inside: Food-safe plastic that melts closed with a heat sealer."
5. In 'reason', explain like a helpful friend: what causes this food to spoil (dampness, air, pests, bad oil smell) and how this packet keeps it crunchy, fresh, and flavorful.
6. In 'barrier_needs', rate protection needs (High, Medium, or Low) for Moisture (water/dampness), Oxygen (air/spoilage), and Light (sunlight/heat).
7. In 'low_cost_alternative', provide an affordable, easy-to-find budget option available in local wholesale markets.
8. In 'sustainable_alternative', provide an eco-friendly or recyclable option in plain words.
9. In 'assumptions', provide practical tips for small producers (e.g. using a hand heat-sealer tightly, storing bags off cold damp floors, etc.).

OUTPUT FORMAT:
Respond strictly with a valid JSON object. No markdown text outside the JSON.
Follow this exact structure:
{
  "identified_food": "Potato Chips",
  "confidence": "High | Medium | Low",
  "estimated_shelf_life": "6 months in a cool, dry place away from sun",
  "recommended_material": "Shiny Silver Foil Snack Pouch (Airtight Metallized BOPP)",
  "packaging_structure": "Outside: Printed plastic film + Middle: Shiny silver foil to block air & sun + Inside: Food-safe heat-sealing layer",
  "reason": "Potato chips lose their crunch if exposed to damp air and develop a bad oily smell if exposed to oxygen. The silver foil lining blocks air, moisture, and sunlight completely.",
  "barrier_needs": {
    "moisture_protection": "High",
    "oxygen_protection": "High",
    "light_protection": "High"
  },
  "low_cost_alternative": "Thick plastic pillow pouch (HDPE/LDPE) sealed tightly with a hand heat sealer",
  "sustainable_alternative": "100% recyclable all-plastic pouch (Mono-PE) or brown paper bag with plant-based lining",
  "assumptions": [
    "Use an electric heat-sealer at the right temperature so there are no tiny air leaks",
    "Store sealed packets in a cool, dry room off the floor on wooden pallets",
    "Test a small batch for 2 weeks before packing your whole harvest"
  ]
}
"""


def safe_extract_json(text: str) -> dict:
    """
    Safely extracts and parses a JSON object from Gemini response text.
    Handles raw JSON, markdown fences (```json ... ```), preamble, and commentary.
    """
    if not text or not text.strip():
        raise ValueError("AI response text was empty.")

    cleaned = text.strip()

    # 1. Direct JSON parse
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # 2. Extract from markdown code block (```json ... ``` or ``` ... ```)
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(1).strip())
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    # 3. Locate outermost curly braces { ... }
    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        json_candidate = cleaned[first_brace:last_brace + 1].strip()
        try:
            parsed = json.loads(json_candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Failed to parse AI output into valid JSON. Received:\n{cleaned[:200]}")


def ensure_recommendation_schema(data: dict, fallback_food_name: str = "", shelf_life: str = "") -> dict:
    """
    Ensures all 10 required fields are present in the response dictionary.
    """
    if not isinstance(data, dict):
        data = {}

    food = data.get("identified_food", "").strip()

    # If food is empty, fallback to manual food name or warning message
    if not food:
        if fallback_food_name:
            food = fallback_food_name.strip()
        else:
            food = "Food could not be identified confidently. Please enter the food name manually."

    # Normalization: if image was identified as potato chips, ensure canonical title
    if any(term in food.lower() for term in ["potato chip", "potato crisps", "chips", "crisps"]) and "could not be identified" not in food.lower():
        food = "Potato Chips"

    # Shelf life field (ensure both estimated_shelf_life and expected_shelf_life are set)
    shelf = data.get("estimated_shelf_life") or data.get("expected_shelf_life") or (f"{shelf_life} (estimated)" if shelf_life else "1–3 months")

    barrier_needs = data.get("barrier_needs")
    if not isinstance(barrier_needs, dict):
        barrier_needs = {
            "moisture_protection": "High",
            "oxygen_protection": "High",
            "light_protection": "Medium"
        }
    else:
        barrier_needs = {
            "moisture_protection": str(barrier_needs.get("moisture_protection", "High")),
            "oxygen_protection": str(barrier_needs.get("oxygen_protection", "High")),
            "light_protection": str(barrier_needs.get("light_protection", "Medium"))
        }

    assumptions = data.get("assumptions")
    if not isinstance(assumptions, list) or len(assumptions) == 0:
        assumptions = [
            "Packaging process maintains strict food-grade hygienic conditions.",
            "Seal integrity and barrier performance must be validated via laboratory testing.",
            "Shelf-life estimates are advisory and subject to storage humidity and temperature control."
        ]

    return {
        "identified_food": food,
        "confidence": str(data.get("confidence", "High")).strip(),
        "estimated_shelf_life": str(shelf).strip(),
        "expected_shelf_life": str(shelf).strip(),
        "recommended_material": str(data.get("recommended_material", "Multi-layer Metallized Barrier Laminate")).strip(),
        "packaging_structure": str(data.get("packaging_structure", "Outer Printable Layer + Core Barrier Layer + Sealing Film")).strip(),
        "reason": str(data.get("reason", f"Selected for optimal barrier protection against moisture and oxygen.")).strip(),
        "barrier_needs": barrier_needs,
        "low_cost_alternative": str(data.get("low_cost_alternative", "Co-extruded LDPE/HDPE pouch with airtight zip closure")).strip(),
        "sustainable_alternative": str(data.get("sustainable_alternative", "Recyclable mono-material PE laminate or bio-based PLA film")).strip(),
        "assumptions": [str(a) for a in assumptions]
    }


def call_gemini_with_fallback(api_key: str, payload: dict, timeout_per_model: int = 18, delay_between_models: float = 0.4) -> tuple:
    """
    Executes a Gemini API call with automatic multi-model failover.
    If a model hits high demand (503), rate limiting (429), or server errors (500, 502, 504),
    it immediately switches to an alternative model in the pool with a tiny delay to keep responses fast.
    
    Returns:
        (response_json: dict, successful_model_name: str)
    """
    candidate_models = get_candidate_models()
    errors_summary = []

    # Attempt models in priority order
    for idx, model_name in enumerate(candidate_models):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        try:
            print(f"[INFO] Calling Gemini API (model: '{model_name}')...")
            response = requests.post(url, json=payload, timeout=timeout_per_model)

            # Check for high demand (503), rate limit (429), or server transient errors (500, 502, 504)
            if response.status_code in (503, 429, 500, 502, 504):
                status_desc = {
                    503: "High Demand / Overloaded",
                    429: "Rate Limit / Quota Exceeded",
                    500: "Internal Error",
                    502: "Bad Gateway",
                    504: "Gateway Timeout"
                }.get(response.status_code, "Server Error")

                error_detail = response.text[:180]
                print(f"[WARN] Model '{model_name}' returned HTTP {response.status_code} ({status_desc}): {error_detail}", file=sys.stderr)
                errors_summary.append(f"{model_name}: HTTP {response.status_code} ({status_desc})")

                # If there are other models available, insert a tiny micro-delay and switch immediately
                if idx < len(candidate_models) - 1:
                    next_model = candidate_models[idx + 1]
                    print(f"[FAST-FAILOVER] Switching to alternate model '{next_model}' (delay {delay_between_models}s)...")
                    if delay_between_models > 0:
                        time.sleep(delay_between_models)
                    continue

            # Check for not found / deprecated model (404) -> skip immediately with no delay
            if response.status_code == 404:
                print(f"[WARN] Model '{model_name}' not available on current API endpoint (HTTP 404). Trying next...", file=sys.stderr)
                errors_summary.append(f"{model_name}: HTTP 404 (Not Found)")
                continue

            if response.status_code != 200:
                print(f"\n[GEMINI API ERROR] Model '{model_name}' HTTP {response.status_code}: {response.text}\n", file=sys.stderr)
                errors_summary.append(f"{model_name}: HTTP {response.status_code}")
                # If non-fatal, try next candidate
                if idx < len(candidate_models) - 1:
                    continue
                response.raise_for_status()

            data = response.json()
            candidates = data.get("candidates", [])
            if not candidates:
                print(f"[WARN] Model '{model_name}' returned no candidates.", file=sys.stderr)
                errors_summary.append(f"{model_name}: No candidates returned")
                if idx < len(candidate_models) - 1:
                    continue
                raise ValueError("Gemini API returned no response candidates.")

            print(f"[SUCCESS] Responded successfully using Gemini model: '{model_name}'")
            return data, model_name

        except requests.exceptions.Timeout:
            print(f"[WARN] Model '{model_name}' request timed out (> {timeout_per_model}s).", file=sys.stderr)
            errors_summary.append(f"{model_name}: Timeout")
            if idx < len(candidate_models) - 1:
                next_model = candidate_models[idx + 1]
                print(f"[FAST-FAILOVER] Switching to '{next_model}' after timeout...")
                continue
        except requests.exceptions.RequestException as req_err:
            print(f"[WARN] Network error with model '{model_name}': {req_err}", file=sys.stderr)
            errors_summary.append(f"{model_name}: {str(req_err)}")
            if idx < len(candidate_models) - 1:
                continue

    # Final retry pass with top 2 models after a brief 1.0s delay if everything was busy
    print("[WARN] All candidate models encountered issues. Performing one fast final retry with primary models...", file=sys.stderr)
    time.sleep(1.0)
    for model_name in candidate_models[:2]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        try:
            print(f"[INFO] Final retry with '{model_name}'...")
            response = requests.post(url, json=payload, timeout=20)
            if response.status_code == 200:
                data = response.json()
                if data.get("candidates"):
                    print(f"[SUCCESS] Final retry succeeded with model '{model_name}'")
                    return data, model_name
        except Exception:
            pass

    err_report = " | ".join(errors_summary)
    raise RuntimeError(f"All Gemini models were unavailable or in high demand. Details: {err_report}")


def analyze_food_packaging(image_bytes: bytes = None, image_mime: str = None,
                           food_name: str = "", shelf_life: str = "",
                           storage: str = "", transport: str = "",
                           budget: str = "") -> dict:
    """
    Calls Gemini API with the uploaded image and packaging requirements.
    Automatically switches to alternative Gemini models if a model is under high demand or rate limited.
    """
    load_dotenv(dotenv_path=ENV_PATH)
    api_key = os.getenv("GEMINI_API_KEY", "").strip()

    if not api_key:
        error_msg = "GEMINI_API_KEY is missing from backend/.env. Please add: GEMINI_API_KEY=your_key"
        print(f"\n[ERROR] {error_msg}\n", file=sys.stderr)
        raise RuntimeError(error_msg)

    # Prepare prompt parts
    prompt_text = f"""Analyze this food packaging request and return strict JSON:

User Inputs:
- Manually Provided Food Name: {food_name if food_name else 'None (Identify food from the image)'}
- Target Shelf Life: {shelf_life if shelf_life else 'Standard commercial period'}
- Storage Condition: {storage if storage else 'Ambient room temperature'}
- Transportation Condition: {transport if transport else 'Standard road transport'}
- Budget Priority: {budget if budget else 'Balanced'}

Instructions:
1. If an image is provided:
   - Identify the food accurately. If it is potato chips, identify it as "Potato Chips".
   - If the image is not clear or cannot be identified confidently, set identified_food to:
     "Food could not be identified confidently. Please enter the food name manually."
2. Provide technical material recommendations, layer structure, barrier needs, and alternatives.
3. Output strictly valid JSON conforming to the requested schema.
"""

    parts = []
    if image_bytes and image_mime:
        encoded_image = base64.b64encode(image_bytes).decode("utf-8")
        parts.append({
            "inline_data": {
                "mime_type": image_mime,
                "data": encoded_image
            }
        })
        print(f"[INFO] Sending image to Gemini ({image_mime}, {len(image_bytes)} bytes)...")

    parts.append({"text": prompt_text})

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": parts
            }
        ],
        "systemInstruction": {
            "parts": [
                {"text": SYSTEM_INSTRUCTION}
            ]
        },
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2
        }
    }

    try:
        data, used_model = call_gemini_with_fallback(api_key, payload, timeout_per_model=18, delay_between_models=0.4)
        candidates = data.get("candidates", [])
        if not candidates:
            raise ValueError("Gemini API returned no response candidates.")

        candidate = candidates[0]
        text_content = ""
        for part in candidate.get("content", {}).get("parts", []):
            if "text" in part:
                text_content += part["text"]

        extracted = safe_extract_json(text_content)
        result = ensure_recommendation_schema(extracted, fallback_food_name=food_name, shelf_life=shelf_life)
        print(f"[SUCCESS] ({used_model}) Gemini identified food as: '{result['identified_food']}' (Confidence: {result['confidence']})")
        return result

    except Exception as exc:
        print(f"\n[BACKEND ERROR] Gemini API processing failed: {exc}\n", file=sys.stderr)
        traceback.print_exc()
        raise RuntimeError(f"Gemini API Error: {str(exc)}") from exc


def chat_with_wrapshield(messages: list, new_message: str, current_food_details: dict = None) -> str:
    """
    Chat consultation with Gemini AI about packaging requirements.
    Uses multi-model fallback to immediately recover if a model experiences high demand.
    """
    load_dotenv(dotenv_path=ENV_PATH)
    api_key = os.getenv("GEMINI_API_KEY", "").strip()

    if not api_key:
        error_msg = "GEMINI_API_KEY is missing from backend/.env."
        print(f"[ERROR] {error_msg}", file=sys.stderr)
        return "The packaging assistant is offline. Please set GEMINI_API_KEY in backend/.env to enable chat."

    context_str = ""
    if current_food_details:
        context_str = f"\nActive Product Context:\n{json.dumps(current_food_details, indent=2)}"

    system_prompt = (
        "You are WrapShield AI, an expert food packaging consultant. "
        "Answer questions on packaging materials, sealing, barrier requirements, shelf-life, and pouch formats. "
        "Keep answers concise, actionable, and friendly."
        f"{context_str}"
    )

    contents = []
    current_role = None

    if isinstance(messages, list):
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = "user" if msg.get("sender") == "user" else "model"
            text = str(msg.get("text", "")).strip()
            if not text:
                continue

            if role == current_role and contents:
                contents[-1]["parts"][0]["text"] += f"\n{text}"
            else:
                contents.append({"role": role, "parts": [{"text": text}]})
                current_role = role

    if contents and contents[0]["role"] == "model":
        contents.insert(0, {"role": "user", "parts": [{"text": "Hello WrapShield, I need packaging guidance."}]})

    if contents and contents[-1]["role"] == "user":
        contents[-1]["parts"][0]["text"] += f"\n{new_message}"
    else:
        contents.append({"role": "user", "parts": [{"text": new_message}]})

    payload = {
        "contents": contents,
        "systemInstruction": {
            "parts": [{"text": system_prompt}]
        },
        "generationConfig": {
            "temperature": 0.5,
            "maxOutputTokens": 800
        }
    }

    try:
        data, used_model = call_gemini_with_fallback(api_key, payload, timeout_per_model=15, delay_between_models=0.3)
        candidates = data.get("candidates", [])
        if not candidates:
            return "No response received from AI assistant."

        reply = ""
        for part in candidates[0].get("content", {}).get("parts", []):
            if "text" in part:
                reply += part["text"]
        return reply.strip() or "Thank you for your question. How else can I assist with your packaging?"

    except Exception as err:
        print(f"[CHAT ERROR] Exception during chat: {err}", file=sys.stderr)
        return f"Unable to reach Gemini AI: {str(err)}. Check terminal for details."


# Backwards compatibility alias
chat_with_packsmart = chat_with_wrapshield


