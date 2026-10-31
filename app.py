import hashlib
import os
import random
import re
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from flask import Flask, render_template, request, jsonify
from groq import Groq, RateLimitError


# ----- Users, daily limit aur referral (database) -----
DB_URL = os.environ.get("DATABASE_URL", "").strip()
PG = DB_URL.startswith(("postgres://", "postgresql://"))
if PG:
    import psycopg2

FREE_DAILY = int(os.environ.get("FREE_DAILY_LIMIT", "20"))   # roz ke free messages
REF_BONUS = int(os.environ.get("REF_BONUS", "10"))           # dost db_join kare to referrer ko
WELCOME_BONUS = int(os.environ.get("WELCOME_BONUS", "5"))    # naye user ko
MAX_REFS = int(os.environ.get("MAX_REFS", "20"))             # ek user max itne dost se bonus le sakta hai
SALT = os.environ.get("IP_SALT", "kayth-ip-salt")
UID_RE = re.compile(r"^[A-Za-z0-9_-]{10,40}$")


def db_run(sql, args=(), fetch=None):
    con = psycopg2.connect(DB_URL) if PG else sqlite3.connect(os.environ.get("SQLITE_PATH", "kayth.db"))
    try:
        cur = con.cursor()
        cur.execute(sql.replace("?", "%s") if PG else sql, args)
        out = cur.fetchone() if fetch == "one" else cur.fetchall() if fetch == "all" else None
        con.commit()
        return out
    finally:
        con.close()


def db_init():
    db_run("CREATE TABLE IF NOT EXISTS kusers (uid TEXT PRIMARY KEY, code TEXT UNIQUE NOT NULL, ref_by TEXT, "
        "ip TEXT, bonus INTEGER NOT NULL DEFAULT 0, refs INTEGER NOT NULL DEFAULT 0, created BIGINT NOT NULL)")
    db_run("CREATE TABLE IF NOT EXISTS kusage (uid TEXT NOT NULL, day TEXT NOT NULL, "
        "n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (uid, day))")
    db_run("CREATE TABLE IF NOT EXISTS krefs (referrer TEXT NOT NULL, ip TEXT NOT NULL, PRIMARY KEY (referrer, ip))")


def db_valid_uid(u):
    return isinstance(u, str) and bool(UID_RE.match(u))


def db_ip_hash(ip):
    return hashlib.sha256((SALT + (ip or "")).encode()).hexdigest()[:16]


def db_today():
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d")


def db_user(uid):
    r = db_run("SELECT code, bonus, refs, ip FROM kusers WHERE uid=?", (uid,), "one")
    return {"code": r[0], "bonus": r[1], "refs": r[2], "ip": r[3]} if r else None


def db_create(uid, h, ref_by=None, bonus=0):
    for _ in range(5):
        try:
            db_run("INSERT INTO kusers (uid, code, ref_by, ip, bonus, created) VALUES (?,?,?,?,?,?)",
                (uid, secrets.token_hex(3).upper(), ref_by, h, bonus, int(time.time())))
            return
        except Exception:
            if db_user(uid):
                return


def db_me(uid):
    u = db_user(uid)
    if not u:
        return None
    row = db_run("SELECT n FROM kusage WHERE uid=? AND day=?", (uid, db_today()), "one")
    free_left = max(0, FREE_DAILY - (row[0] if row else 0))
    return {"code": u["code"], "bonus": u["bonus"], "refs": u["refs"], "left": free_left + u["bonus"],
            "free_left": free_left, "free_limit": FREE_DAILY, "ref_bonus": REF_BONUS,
            "welcome_bonus": WELCOME_BONUS, "max_refs": MAX_REFS}


def db_join(uid, ref, ip):
    """Naya user banao aur (agar valid ho) referral bonus do. (db_me, credited) lautata hai."""
    if db_user(uid):
        return db_me(uid), False
    h = db_ip_hash(ip)
    credited, ruid, bonus = False, None, 0
    ref = (ref or "").strip().upper()[:12]
    if ref:
        r = db_run("SELECT uid, refs, ip FROM kusers WHERE code=?", (ref,), "one")
        if r and r[0] != uid:
            ruid, refs, rip = r
            seen = db_run("SELECT 1 FROM krefs WHERE referrer=? AND ip=?", (ruid, h), "one")
            # same network/device se referral pe bonus nahi, ek IP se ek hi baar
            if refs < MAX_REFS and rip != h and not seen:
                credited, bonus = True, WELCOME_BONUS
    db_create(uid, h, ruid if credited else None, bonus)
    if credited:
        db_run("UPDATE kusers SET bonus = bonus + ?, refs = refs + 1 WHERE uid=?", (REF_BONUS, ruid))
        try:
            db_run("INSERT INTO krefs (referrer, ip) VALUES (?,?)", (ruid, h))
        except Exception:
            pass
    return db_me(uid), credited


def db_consume(uid, ip):
    """1 message kharch karo. (ok, source, left) lautata hai."""
    if not db_user(uid):
        db_create(uid, db_ip_hash(ip))
    m = db_me(uid)
    if m["free_left"] > 0:
        db_run("INSERT INTO kusage (uid, day, n) VALUES (?,?,1) ON CONFLICT (uid, day) DO UPDATE SET n = kusage.n + 1",
            (uid, db_today()))
        return True, "free", m["left"] - 1
    if m["bonus"] > 0:
        db_run("UPDATE kusers SET bonus = bonus - 1 WHERE uid=? AND bonus > 0", (uid,))
        return True, "bonus", m["left"] - 1
    return False, None, 0


def db_refund(uid, source):
    if source == "free":
        db_run("UPDATE kusage SET n = n - 1 WHERE uid=? AND day=? AND n > 0", (uid, db_today()))
    elif source == "bonus":
        db_run("UPDATE kusers SET bonus = bonus + 1 WHERE uid=?", (uid,))


app = Flask(__name__)

try:
    db_init()
except Exception:
    app.logger.exception("Database init fail (limit/refer band rahega, chat chalti rahegi)")


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
RATE_LIMIT_REPLY = "Bohot log mujhse baat kar rahe hain 😭 thoda ruk ke bhej, abhi line lambi hai!"
NO_KEY_REPLY = "Boss ne meri API key lagayi hi nahi 😂 admin se bolo GROQ_API_KEY set kare!"
LIMIT_REPLY = "Aaj ke free messages khatam 😅 kal phir aa, ya dost ko refer karke extra messages kama le 🎁"
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


def complete(models, messages, max_tokens=800):
    """Models ko ek ek karke try karta hai, pehla jo chale uska reply deta hai."""
    last = None
    for model in models:
        try:
            kwargs = dict(model=model, messages=messages, max_tokens=max_tokens, temperature=0.8)
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


def client_ip():
    return request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or ""


def charge():
    """(allowed, uid, source, left). Database kharab ho to user ko rokte nahi."""
    uid = request.headers.get("X-Uid", "")
    if not db_valid_uid(uid):
        return True, None, None, None
    try:
        ok, src, left = db_consume(uid, client_ip())
        return ok, uid, src, left
    except Exception:
        app.logger.exception("charge failed")
        return True, None, None, None


def give_back(uid, src, left):
    """Groq fail hua to message wapas kar do."""
    if not uid or not src:
        return left
    try:
        db_refund(uid, src)
        return None if left is None else left + 1
    except Exception:
        app.logger.exception("refund failed")
        return left


@app.route("/api/join", methods=["POST"])
def api_join():
    uid = request.headers.get("X-Uid", "")
    if not db_valid_uid(uid):
        return jsonify({"error": "bad uid"}), 400
    data = request.get_json(silent=True) or {}
    try:
        m, credited = db_join(uid, str(data.get("ref", ""))[:20], client_ip())
    except Exception:
        app.logger.exception("join failed")
        return jsonify({"error": "db"}), 503
    m["credited"] = credited
    return jsonify(m)


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

    ok, uid, src, left = charge()
    if not ok:
        return jsonify({"reply": LIMIT_REPLY, "limit": True, "left": 0})

    prompt = message
    if client is not None:
        try:
            prompt = complete(
                TEXT_MODELS,
                [{"role": "system", "content": IMAGE_SYSTEM}, {"role": "user", "content": message}],
            )
        except Exception:
            app.logger.exception("Image prompt rewrite failed")

    prompt = " ".join(prompt.split()).strip("\"'")[:300]
    if not prompt or prompt.upper().startswith("REFUSE"):
        return jsonify({"reply": random.choice(IMAGE_REFUSE), "refused": True, "left": give_back(uid, src, left)})

    # Pollinations ka free endpoint: browser seedha image load karta hai
    url = "https://image.pollinations.ai/prompt/%s?width=768&height=768&nologo=true&safe=true&seed=%d" % (
        quote(prompt, safe=""),
        random.randint(1, 999999),
    )
    return jsonify({"url": url, "prompt": prompt, "left": left})


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
    for model in TEXT_MODELS + VISION_MODELS:
        try:
            t = complete([model], [{"role": "user", "content": "Say hi in 3 words"}], 1500)
            lines.append("OK   %s -> %s" % (model, t[:60]))
        except Exception as e:
            lines.append("FAIL %s -> %s: %s" % (model, type(e).__name__, str(e)[:200]))
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

    ok, uid, src, left = charge()
    if not ok:
        return jsonify({"reply": LIMIT_REPLY, "limit": True, "left": 0})

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + clean_history(data.get("history")) + [user_msg]

    try:
        return jsonify({"reply": complete(models, messages, 2000 if image else 800), "left": left})
    except RateLimitError:
        return jsonify({"reply": RATE_LIMIT_REPLY, "fallback": True, "err": "RateLimitError", "left": give_back(uid, src, left)})
    except Exception as e:
        app.logger.exception("Groq call failed")
        return jsonify({"reply": random.choice(FALLBACKS), "fallback": True, "err": type(e).__name__, "left": give_back(uid, src, left)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
