import os
import random

from flask import Flask, render_template, request, jsonify
from groq import Groq, RateLimitError

app = Flask(__name__)

MODEL = "llama-3.1-8b-instant"
API_KEY = os.environ.get("GROQ_API_KEY")
client = Groq(api_key=API_KEY) if API_KEY else None

SYSTEM_PROMPT = (
    "You are Kayth AI, created by Dipanshu Kayth, 16yo coder from Siwani, Haryana. "
    "You are NOT ChatGPT or Meta AI. You talk in Hinglish, funny, Gen-Z, max 3 lines. "
    "If user says 'I am Dipanshu' or 'boss' or 'creator' then say "
    "'Ha boss Dipanshu! Bolo kya kaam hai 😎'. Never say you are made by OpenAI."
)

BOSS_REPLY = "Ha boss Dipanshu! Bolo kya kaam hai 😎"
BOSS_TRIGGERS = {"boss", "creator", "i am dipanshu", "i am dipanshu kayth", "main dipanshu hu", "main dipanshu hoon"}

FALLBACKS = [
    "Bhai mera dimaag thoda hang ho gaya 😵 ek baar phir bhej na!",
    "Server ne chai break le liya ☕ 5 sec baad try kar!",
    "Oops, signal gaya tel lene 📡 dobara bol, is baar pakka sunuga.",
    "Brain.exe has stopped working 💀 thodi der baad aa, main reboot ho raha hu.",
]
RATE_LIMIT_REPLY = "Bohot log mujhse baat kar rahe hain 😭 thoda ruk ke bhej, abhi line lambi hai!"
NO_KEY_REPLY = "Boss ne meri API key lagayi hi nahi 😂 admin se bolo GROQ_API_KEY set kare!"


def clean_history(history):
    out = []
    if not isinstance(history, list):
        return out
    for m in history[-10:]:
        if (
            isinstance(m, dict)
            and m.get("role") in ("user", "assistant")
            and isinstance(m.get("content"), str)
            and m["content"].strip()
        ):
            out.append({"role": m["role"], "content": m["content"][:1000]})
    return out


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/health")
def health():
    return "ok", 200


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    message = data.get("message")
    if not isinstance(message, str) or not message.strip():
        return jsonify({"reply": "Kuch likh to sahi bhai 😅"}), 400
    message = message.strip()[:1000]

    if message.lower().rstrip("!. ") in BOSS_TRIGGERS:
        return jsonify({"reply": BOSS_REPLY})

    if client is None:
        return jsonify({"reply": NO_KEY_REPLY, "fallback": True})

    messages = (
        [{"role": "system", "content": SYSTEM_PROMPT}]
        + clean_history(data.get("history"))
        + [{"role": "user", "content": message}]
    )

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_tokens=200,
            temperature=0.8,
        )
        reply = (resp.choices[0].message.content or "").strip()
        if not reply:
            raise ValueError("empty reply")
        return jsonify({"reply": reply})
    except RateLimitError:
        return jsonify({"reply": RATE_LIMIT_REPLY, "fallback": True})
    except Exception:
        app.logger.exception("Groq call failed")
        return jsonify({"reply": random.choice(FALLBACKS), "fallback": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
