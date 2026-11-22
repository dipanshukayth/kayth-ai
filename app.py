import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
import os
import json
import random
import re
import threading
import time
from collections import defaultdict, deque
from urllib.parse import quote

from flask import Flask, render_template, request, jsonify
from groq import Groq, RateLimitError


app = Flask(__name__)


def env(name, default=""):
    # Render me paste karte time space ya quotes aa jaate hain, unhe hata do
    return os.environ.get(name, default).strip().strip("'\"").strip()


API_KEY = env("GROQ_API_KEY")
FAL_KEY = env("FAL_KEY")
FAL_IMAGE_MODEL = env("FAL_IMAGE_MODEL", "fal-ai/flux-2/turbo")
FAL_VIDEO_TEXT_MODEL = "fal-ai/wan/v2.7/text-to-video"
FAL_VIDEO_IMAGE_MODEL = "fal-ai/wan/v2.7/image-to-video"
DEBUG_KEY = env("DEBUG_KEY")   # /debug tabhi khulega jab ye set ho: /debug?k=<DEBUG_KEY>
client = Groq(api_key=API_KEY) if API_KEY else None

# llama-3.1-8b-instant Groq ne 16 Aug 2026 ko band kar diya.
# Replacement: openai/gpt-oss-20b. Pehla fail ho to agla try hota hai.
_models = [env("GROQ_MODEL"), "openai/gpt-oss-20b", "openai/gpt-oss-120b"]
TEXT_MODELS = list(dict.fromkeys(m for m in _models if m))
# Photo samajhne wala model (Groq pe Preview tier). Env se badal sakte ho.
VISION_MODELS = list(dict.fromkeys(m for m in [env("GROQ_VISION_MODEL"), "qwen/qwen3.8-27b", "meta-models/muse-spark-open"] if m))

SYSTEM_PROMPT = (
    "You are Kayth AI, created by Dipanshu Kayth, 16yo coder from Isharwal, Bhiwani, Haryana. Your creator is Dipanshu Kayth. If asked who created, made, built, or owns you, answer Dipanshu Kayth. Never claim OpenAI, ChatGPT, or a model provider created you; they only provide the underlying model/service. "
    "You are NOT ChatGPT or Meta AI. You talk in Hinglish, funny, Gen-Z, max 3 lines. "
    "If user says 'I am Dipanshu' or 'boss' or 'creator' then say "
    "'Ha boss Dipanshu! Bolo kya kaam hai 😎'. Never say you are made by OpenAI. "
    "Rules: Reply only as Kayth AI, fully in character. Never add notes, disclaimers, hashtags or comments "
    "about your own reply or style (no '(Note: ...)'). Max 3 short lines. "
    "Roasts and jokes must stay playful: never target anyone's family, religion, caste, gender, body or health. "
    "If the user asks something serious (health, legal, money, safety), answer carefully and helpfully in the same "
    "Hinglish tone, without jokes."
)

SHAYAR_PROMPT = """
You are Kayth AI Shayar Mode 🌹. Your creator and developer is Dipanshu Kayth. If asked who created, made, built, or owns you, clearly answer that your creator is Dipanshu Kayth. Never claim that OpenAI, ChatGPT, or any AI model provider created you; those are only model/service providers. Always answer the user's actual request helpfully, but express the answer as Hindi/Urdu shayari. For serious topics, keep the advice clear and careful while using poetic couplets. If the user is Dipanshu or says boss/creator, address them warmly in shayari.

Always reply in Hindi/Urdu shayari.

Types:
- Romantic ❤️
- Sad 💔
- Friendship 🤝
- Attitude 😎
- Motivational ✨

Rules:
- 2 to 4 lines only.
- Reply only as shayari.
- No explanations.
- No notes.
- Rhyming style.
- Emotional and poetic.
"""
BOSS_REPLY = "Ha boss Dipanshu! Bolo kya kaam hai 😎"
SHAYAR_BOSS_REPLY = "Dipanshu boss, aapka hukm sar aankhon par 🌹\nBatao kya kaam hai, lafzon se kar doon asar 😎"
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
    for m in history[-6:]:
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
    # model kabhi kabhi aakhir me "(Note: ...)" jod deta hai, use hata do
    text = re.sub(r"\s*\((?:note|nb|p\.s\.?)[^)]*\)\s*$", "", text.strip(), flags=re.IGNORECASE)
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


# ----- Per-IP limits: ek banda poora Groq quota na kha jaye -----
# (per minute, per day). Render ke env se badal sakte ho, jaise LIMIT_CHAT_PER_DAY=40
LIMITS = {
    "chat": (int(env("LIMIT_CHAT_PER_MIN", "5")), int(env("LIMIT_CHAT_PER_DAY", "30"))),
    "photo": (int(env("LIMIT_PHOTO_PER_MIN", "1")), int(env("LIMIT_PHOTO_PER_DAY", "3"))),
    "image": (int(env("LIMIT_IMAGE_PER_MIN", "3")), int(env("LIMIT_IMAGE_PER_DAY", "10"))),
    "video": (int(env("LIMIT_VIDEO_PER_MIN", "1")), int(env("LIMIT_VIDEO_PER_DAY", "2"))),
}
LIMIT_MSG = {
    "chat": ("Thoda dheere bhai 😅 1 minute mein itne messages nahi chalte, thodi der ruk ke bhej.",
             "Aaj ke free messages khatam 😅 kal phir aa, tab tak naye messages ke liye refresh mat kar!"),
    "photo": ("Photo thodi der baad bhejna 📸 abhi pichli wali ka kaam chal raha hai.",
              "Aaj ke free photo-checks khatam 📸 kal phir bhej!"),
    "image": ("Itni jaldi nahi bhai 🎨 thodi der baad phir bol.",
              "Aaj ki free images khatam 🎨 kal phir bana dunga!"),
    "video": ("Video queue busy hai 🎬 ek minute baad try kar.",
              "Aaj ke video generations khatam 🎬 kal phir try kar!"),
}
_hits = defaultdict(deque)
_lock = threading.Lock()


def client_ip():
    return request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or "?"


def hit(kind):
    """(ok, message, token). Limit ke andar ho to 1 gin leta hai."""
    key, now = (client_ip(), kind), time.time()
    per_min, per_day = LIMITS[kind]
    with _lock:
        q = _hits[key]
        while q and now - q[0] > 86400:
            q.popleft()
        if len(q) >= per_day:
            return False, LIMIT_MSG[kind][1], None
        if sum(1 for t in q if now - t < 60) >= per_min:
            return False, LIMIT_MSG[kind][0], None
        q.append(now)
        if len(_hits) > 5000:   # purane IPs saaf karo
            for k in [k for k, d in _hits.items() if not d or now - d[-1] > 86400]:
                del _hits[k]
        return True, None, (key, now)


def give_back(token):
    """Groq fail hua to gin wapas kar do."""
    if not token:
        return
    key, ts = token
    with _lock:
        q = _hits.get(key)
        if q and ts in q:
            q.remove(ts)


def file_note(f):
    name = str(f.get("name", ""))[:80]
    text = f.get("text") if isinstance(f.get("text"), str) else ""
    if text.strip():
        return "\n\n[User ne file bheji: %s]\n```\n%s\n```" % (name, text[:6000])
    return (
        "\n\n[User ne file '%s' (%s) bheji hai, par uska content padh nahi sakte. "
        "User ko honestly batao ki file khol nahi paye.]" % (name, str(f.get("type", ""))[:60])
    )


@app.route("/")
def home():
    return render_template("index.html")


IMAGE_SYSTEM = """
Create a detailed, model-ready image prompt in English from the user's idea. Preserve every requested subject, setting, action, and any exact text. Specify a clear composition and camera framing, distinctive visual style, realistic lighting, color palette, material/texture detail, background, and mood. Make it vivid and coherent, around 60-100 words. Do not add unrelated objects or change the subject. For text in the image, quote the exact words and say they must be legible. If the request is sexual, graphic violence, or a real named person's likeness, output exactly REFUSE.
"""
IMAGE_REFUSE = [
    "Ye wali image main nahi bana sakta bhai 🙅 kuch aur try kar!",
    "Arre isme panga hai 😅 koi aur idea de, wo bana dunga!",
]


def fal_json(url, payload=None, timeout=90):
    if not FAL_KEY:
        raise RuntimeError("FAL_KEY is not configured")
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Authorization": "Key " + FAL_KEY, "Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


@app.route("/image", methods=["POST"])
def image():
    data = request.get_json(silent=True) or {}
    message = data.get("message")
    if not isinstance(message, str) or not message.strip():
        return jsonify({"reply": "Kya banau? Apna idea thoda detail mein likho 🎨"}), 400
    message = message.strip()[:1000]
    ok, msg, token = hit("image")
    if not ok:
        return jsonify({"reply": msg, "limit": True})

    prompt = message
    if client is not None:
        try:
            prompt = complete(
                TEXT_MODELS,
                [{"role": "system", "content": IMAGE_SYSTEM}, {"role": "user", "content": message}],
                500,
                15,
            )
        except Exception:
            app.logger.exception("Image prompt enhancement failed")
    prompt = " ".join(prompt.split()).strip("\"'")[:1200]
    if not prompt or prompt.upper().startswith("REFUSE"):
        give_back(token)
        return jsonify({"reply": random.choice(IMAGE_REFUSE), "refused": True})

    if FAL_KEY:
        try:
            result = fal_json("https://fal.run/%s" % FAL_IMAGE_MODEL, {
                "prompt": prompt,
                "image_size": "square_hd",
                "num_images": 1,
                "enable_prompt_expansion": True,
                "enable_safety_checker": True,
                "output_format": "png",
            })
            images = result.get("images") or []
            if images and images[0].get("url"):
                return jsonify({"url": images[0]["url"], "prompt": result.get("prompt") or prompt, "model": FAL_IMAGE_MODEL})
            raise RuntimeError("Image provider returned no image")
        except Exception as e:
            app.logger.exception("Fal image generation failed")
            give_back(token)
            return jsonify({"reply": "Image provider se image nahi ban payi 😕 thodi der baad try karo.", "err": type(e).__name__}), 502

    url = "https://image.pollinations.ai/prompt/%s?width=1024&height=1024&nologo=true&safe=true&seed=%d" % (
        quote(prompt, safe=""), random.randint(1, 999999),
    )
    return jsonify({"url": url, "prompt": prompt, "model": "pollinations-fallback"})


@app.route("/video", methods=["POST"])
def video():
    if not FAL_KEY:
        return jsonify({"reply": "AI video ke liye Render mein FAL_KEY secret set karna hoga 🎬"}), 503
    data = request.get_json(silent=True) or {}
    message = data.get("message")
    image = data.get("image")
    if not isinstance(message, str) or not message.strip():
        return jsonify({"reply": "Video mein kya dikhana hai? /video ke baad idea likho 🎬"}), 400
    message = message.strip()[:1000]
    if image is not None and not (isinstance(image, str) and re.match(r"^data:image/(jpeg|jpg|png|webp);base64,", image) and len(image) < 6_000_000):
        return jsonify({"reply": BAD_IMAGE_REPLY}), 400
    ok, msg, token = hit("video")
    if not ok:
        return jsonify({"reply": msg, "limit": True})
    model = FAL_VIDEO_IMAGE_MODEL if image else FAL_VIDEO_TEXT_MODEL
    payload = {"prompt": message, "duration": 5, "resolution": "720p", "enable_prompt_expansion": True, "enable_safety_checker": True}
    if image:
        payload["image_url"] = image
    else:
        payload["aspect_ratio"] = "9:16"
    try:
        result = fal_json("https://queue.fal.run/%s" % model, payload, timeout=30)
        request_id = result.get("request_id")
        if not request_id:
            raise RuntimeError("Video provider returned no request id")
        return jsonify({"video_job": True, "request_id": request_id, "image_to_video": bool(image)})
    except Exception as e:
        app.logger.exception("Fal video submit failed")
        give_back(token)
        return jsonify({"reply": "Video request bhej nahi paya 😕 API key/billing check karke phir try karo.", "err": type(e).__name__}), 502


@app.route("/video/status", methods=["POST"])
def video_status():
    if not FAL_KEY:
        return jsonify({"reply": "AI video ke liye Render mein FAL_KEY secret set karna hoga 🎬"}), 503
    data = request.get_json(silent=True) or {}
    request_id = data.get("request_id")
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", request_id):
        return jsonify({"reply": "Video request ID galat hai."}), 400
    model = FAL_VIDEO_IMAGE_MODEL if data.get("image_to_video") else FAL_VIDEO_TEXT_MODEL
    root = "https://queue.fal.run/%s/requests/%s" % (model, request_id)
    try:
        status = fal_json(root + "/status", timeout=25)
        state = status.get("status", "")
        if state == "COMPLETED":
            result = fal_json(root, timeout=30)
            url = (result.get("video") or {}).get("url")
            if not url:
                raise RuntimeError("Video provider returned no video URL")
            return jsonify({"done": True, "url": url})
        if state in {"FAILED", "CANCELLED"}:
            return jsonify({"reply": "Video generate nahi ho paya 😕 koi aur prompt try karo.", "failed": True}), 502
        return jsonify({"pending": True, "status": state or "IN_QUEUE"})
    except Exception as e:
        app.logger.exception("Fal video status failed")
        return jsonify({"reply": "Video status check nahi ho paya 😕 thodi der baad try karo.", "err": type(e).__name__}), 502
@app.route("/health")
def health():
    return "ok", 200


@app.route("/debug")
def debug():
    """Browser me kholo: kayth-ai-2.onrender.com/debug. Kaam hone ke baad hata dena."""
    if not DEBUG_KEY:
        return "DEBUG_KEY Render me set nahi hai (ya deploy abhi nahi hua).", 404
    if request.args.get("k") != DEBUG_KEY:
        return "Key galat hai. Link me ?k= ke baad wahi shabd likho jo DEBUG_KEY ki Value me hai.", 404
    lines = [
        "GROQ_API_KEY set: %s" % bool(API_KEY),
        "FAL_KEY set: %s" % bool(FAL_KEY),
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
    mode = str(data.get("mode", "")).strip().lower()
    shayar_mode = mode in {"shayar", "shayari"}
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
        return jsonify({"reply": SHAYAR_BOSS_REPLY if shayar_mode else BOSS_REPLY})

    # Creator ka naam deterministic rakho, taaki model provider ko creator na kahe.
    creator_question = re.search(
        r"\b(who (made|created|built) you|who is your creator|your creator|creator.?s? name|"
        r"naam.*(creator|banaya|banane)|kisne (banaya|banaaya)|tumhe kisne banaya|"
        r"creator ka naam|creator kaa naam|apna creator)\b",
        message.lower(),
    )
    if image is None and creator_question:
        reply = ("Mere creator Dipanshu Kayth hain, yehi meri pehchaan 🌹\nUnke khayaalon se saja hoon, shayari mera andaaz-e-bayaan ✨" if shayar_mode else "Mere creator Dipanshu Kayth hain.")
        return jsonify({"reply": reply})

    if client is None:
        return jsonify({"reply": NO_KEY_REPLY, "fallback": True, "err": "NoKey"})

    ok, msg, token = hit("photo" if image else "chat")
    if not ok:
        return jsonify({"reply": msg, "limit": True})

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

    # Sirf Shayar mode me shayari; baaki modes Kayth AI ke normal style me.
    system_prompt = SHAYAR_PROMPT if shayar_mode else SYSTEM_PROMPT
    messages = (
        [{"role": "system", "content": system_prompt}]
        + clean_history(data.get("history"))
        + [user_msg]
    )
    try:
        return jsonify({"reply": complete(models, messages, 1500 if image else 600)})
    except RateLimitError:
        give_back(token)
        return jsonify({"reply": RATE_LIMIT_REPLY, "fallback": True, "err": "RateLimitError"})
    except Exception as e:
        app.logger.exception("Groq call failed")
        give_back(token)
        return jsonify({"reply": random.choice(FALLBACKS), "fallback": True, "err": type(e).__name__})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)






