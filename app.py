import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
import os
import random
import re
from urllib.parse import quote

from flask import Flask, render_template, request, jsonify
from groq import Groq, RateLimitError


app = Flask(__name__)


def env(name, default=""):
    # Render me paste karte time space ya quotes aa jaate hain, unhe hata do
    return os.environ.get(name, default).strip().strip("'\"").strip()


API_KEY = env("GROQ_API_KEY")
client = Groq(api_key=API_KEY) if API_KEY else None

# llama-3.1-8b-instant Groq ne 16 Aug 2026 ko band kar diya.
# Replacement: openai/gpt-oss-20b. Pehla fail ho to agla try hota hai.
_models = [env("GROQ_MODEL"), "openai/gpt-oss-20b", "openai/gpt-oss-120b"]
TEXT_MODELS = list(dict.fromkeys(m for m in _models if m))
# Photo samajhne wala model (Groq pe Preview tier). Env se badal sakte ho.
VISION_MODELS = list(dict.fromkeys(m for m in [env("GROQ_VISION_MODEL"), "qwen/qwen3.8-27b", "meta-models/muse-spark-open"] if m))

SYSTEM_PROMPT = (
    "You are Kayth AI, created by Dipanshu Kayth, 16yo coder from Isharwal, Bhiwani, Haryana. "
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
NO_KEY_REPLY = "Boss ne meri API key lagayi hi nahi 😂 admin se bolo GROQ_API_KEY set kare!"
RATE_LIMIT_REPLY = "Bohot log mujhse baat kar rahe hain 😭 thoda ruk ke bhej, abhi line lambi hai!"
BAD_IMAGE_REPLY = "Ye photo thodi badi ya galat lag rahi hai 😅 chhoti photo bhej!"


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


def clean_output(text):
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL)
    return text.strip()


def complete(models, messages, max_tokens=800, timeout=25):
    """Models ko ek ek karke try karta hai, pehla jo chale uska reply deta hai."""
    last = None
    for model in models:
        try:
            kwargs = dict(model=model, messages=messages, max_tokens=max_tokens, temperature=0.8, timeout=timeout)
            if model.startswith("openai/gpt-oss"):
                kwargs["extra_body"] = {"reasoning_effort": "low"}
            resp = client.chat.completions.create(**kwargs)
            text = clean_output(resp.choices[0].message.content)
            if text:
                return text
            last = ValueError("empty reply from " + model)
        except Exception as e:
            app.logger.warning("Model %s failed: %s: %s", model, type(e).__name__, e)
            last = e
    raise last or RuntimeError("no model configured")


def file_note(f):
    name = str(f.get("name", ""))[:80]
    text = f.get("text") if isinstance(f.get("text"), str) else ""
    if text.strip():
        return "\n\n[User ne file bheji: %s]\n```\n%s\n```" % (name, text[:12000])
    return (
        "\n\n[User ne file '%s' (%s) bheji hai, par uska content padh nahi sakte. "
        "User ko honestly batao ki file khol nahi paye.]" % (name, str(f.get("type", ""))[:60])
    )


@app.route("/")
def home():
    return render_template("index.html")


IMAGE_SYSTEM = (
    "Turn the user's request into ONE vivid English image-generation prompt, max 40 words "
    "(subject, style, lighting, mood). Output ONLY the prompt, no quotes, no extra words. "
    "If the request is sexual, gory/violent, or depicts a real named person, output exactly: REFUSE"
)
IMAGE_REFUSE = [
    "Ye wali image main nahi bana sakta bhai 🙅 kuch aur try kar!",
    "Arre isme panga hai 😅 koi aur idea de, wo bana dunga!",
]


@app.route("/image", methods=["POST"])
def image():
    data = request.get_json(silent=True) or {}
    message = data.get("message")
    if not isinstance(message, str) or not message.strip():
        return jsonify({"reply": "Kya banau bhai? Thoda describe to kar 🎨"}), 400
    message = message.strip()[:500]

    prompt = message
    if client is not None:
        try:
            prompt = complete(
                TEXT_MODELS,
                [{"role": "system", "content": IMAGE_SYSTEM}, {"role": "user", "content": message}],
                400,
                10,
            )
        except Exception:
            app.logger.exception("Image prompt rewrite failed")

    prompt = " ".join(prompt.split()).strip("\"'")[:300]
    if not prompt or prompt.upper().startswith("REFUSE"):
        return jsonify({"reply": random.choice(IMAGE_REFUSE), "refused": True})

    # Pollinations ka free endpoint: browser seedha image load karta hai
    url = "https://image.pollinations.ai/prompt/%s?width=768&height=768&nologo=true&safe=true&seed=%d" % (
        quote(prompt, safe=""),
        random.randint(1, 999999),
    )
    return jsonify({"url": url, "prompt": prompt})


@app.route("/health")
def health():
    return "ok", 200


@app.route("/debug")
def debug():
    """Browser me kholo: kayth-ai-2.onrender.com/debug. Kaam hone ke baad hata dena."""
    lines = [
        "GROQ_API_KEY set: %s" % bool(API_KEY),
        "Key 'gsk_' se shuru: %s" % API_KEY.startswith("gsk_"),
        "Key length: %d" % len(API_KEY),
        "Text models: %s" % ", ".join(TEXT_MODELS),
        "Vision models: %s" % ", ".join(VISION_MODELS),
        "",
    ]
    if client is None:
        lines.append("Client nahi bana: GROQ_API_KEY Render me set karo.")
        return "\n".join(lines), 200, {"Content-Type": "text/plain; charset=utf-8"}
    def probe(model):
        try:
            t = complete([model], [{"role": "user", "content": "Say hi in 3 words"}], 1000, 20)
            return "OK   %s -> %s" % (model, t[:60])
        except Exception as e:
            return "FAIL %s -> %s: %s" % (model, type(e).__name__, str(e)[:200])

    def probe_image():
        try:
            req = urllib.request.Request("https://image.pollinations.ai/prompt/cat?width=64&height=64&nologo=true&seed=1",
                                         headers={"User-Agent": "Mozilla/5.0"})
            r = urllib.request.urlopen(req, timeout=20)
            return "OK   pollinations -> HTTP %s, %s, %d bytes" % (r.status, r.headers.get("Content-Type"), len(r.read(200000)))
        except urllib.error.HTTPError as e:
            return "FAIL pollinations -> HTTP %s" % e.code
        except Exception as e:
            return "FAIL pollinations -> %s: %s" % (type(e).__name__, str(e)[:150])

    models = TEXT_MODELS + VISION_MODELS
    with ThreadPoolExecutor(max_workers=len(models) + 1) as ex:
        futs = [ex.submit(probe, m) for m in models] + [ex.submit(probe_image)]
        lines.extend(f.result() for f in futs)
    return "\n".join(lines), 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    message = data.get("message")
    image = data.get("image")
    file = data.get("file") if isinstance(data.get("file"), dict) else None
    message = message.strip()[:1000] if isinstance(message, str) else ""

    if image is not None:
        if not (isinstance(image, str) and image.startswith("data:image/") and len(image) < 6_000_000):
            return jsonify({"reply": BAD_IMAGE_REPLY}), 400
        if not message:
            message = "Is photo mein kya hai? Batao."
    elif not message and not file:
        return jsonify({"reply": "Kuch likh to sahi bhai 😅"}), 400
    if file and not message:
        message = "Is file mein kya hai? Short mein batao."

    if image is None and message.lower().rstrip("!. ") in BOSS_TRIGGERS:
        return jsonify({"reply": BOSS_REPLY})

    if client is None:
        return jsonify({"reply": NO_KEY_REPLY, "fallback": True, "err": "NoKey"})

    if image:
        user_msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": message},
                {"type": "image_url", "image_url": {"url": image}},
            ],
        }
        models = VISION_MODELS
    else:
        user_msg = {"role": "user", "content": message + (file_note(file) if file else "")}
        models = TEXT_MODELS

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + clean_history(data.get("history")) + [user_msg]

    try:
        return jsonify({"reply": complete(models, messages, 2000 if image else 800)})
    except RateLimitError:
        return jsonify({"reply": RATE_LIMIT_REPLY, "fallback": True, "err": "RateLimitError"})
    except Exception as e:
        app.logger.exception("Groq call failed")
        return jsonify({"reply": random.choice(FALLBACKS), "fallback": True, "err": type(e).__name__})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
