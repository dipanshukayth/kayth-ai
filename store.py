"""Users, daily limit aur referral ka hisaab.

DATABASE_URL (Postgres, jaise Neon/Supabase) set ho to wo use hota hai.
Warna local SQLite file (Render free pe ye file restart pe mit jaati hai).
"""
import hashlib
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone

DB_URL = os.environ.get("DATABASE_URL", "").strip()
PG = DB_URL.startswith(("postgres://", "postgresql://"))
if PG:
    import psycopg2

FREE_DAILY = int(os.environ.get("FREE_DAILY_LIMIT", "20"))   # roz ke free messages
REF_BONUS = int(os.environ.get("REF_BONUS", "10"))           # dost join kare to referrer ko
WELCOME_BONUS = int(os.environ.get("WELCOME_BONUS", "5"))    # naye user ko
MAX_REFS = int(os.environ.get("MAX_REFS", "20"))             # ek user max itne dost se bonus le sakta hai
SALT = os.environ.get("IP_SALT", "kayth-ip-salt")
UID_RE = re.compile(r"^[A-Za-z0-9_-]{10,40}$")


def run(sql, args=(), fetch=None):
    con = psycopg2.connect(DB_URL) if PG else sqlite3.connect(os.environ.get("SQLITE_PATH", "kayth.db"))
    try:
        cur = con.cursor()
        cur.execute(sql.replace("?", "%s") if PG else sql, args)
        out = cur.fetchone() if fetch == "one" else cur.fetchall() if fetch == "all" else None
        con.commit()
        return out
    finally:
        con.close()


def init():
    run("CREATE TABLE IF NOT EXISTS kusers (uid TEXT PRIMARY KEY, code TEXT UNIQUE NOT NULL, ref_by TEXT, "
        "ip TEXT, bonus INTEGER NOT NULL DEFAULT 0, refs INTEGER NOT NULL DEFAULT 0, created BIGINT NOT NULL)")
    run("CREATE TABLE IF NOT EXISTS kusage (uid TEXT NOT NULL, day TEXT NOT NULL, "
        "n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (uid, day))")
    run("CREATE TABLE IF NOT EXISTS krefs (referrer TEXT NOT NULL, ip TEXT NOT NULL, PRIMARY KEY (referrer, ip))")


def valid_uid(u):
    return isinstance(u, str) and bool(UID_RE.match(u))


def ip_hash(ip):
    return hashlib.sha256((SALT + (ip or "")).encode()).hexdigest()[:16]


def today():
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d")


def _user(uid):
    r = run("SELECT code, bonus, refs, ip FROM kusers WHERE uid=?", (uid,), "one")
    return {"code": r[0], "bonus": r[1], "refs": r[2], "ip": r[3]} if r else None


def _create(uid, h, ref_by=None, bonus=0):
    for _ in range(5):
        try:
            run("INSERT INTO kusers (uid, code, ref_by, ip, bonus, created) VALUES (?,?,?,?,?,?)",
                (uid, secrets.token_hex(3).upper(), ref_by, h, bonus, int(time.time())))
            return
        except Exception:
            if _user(uid):
                return


def me(uid):
    u = _user(uid)
    if not u:
        return None
    row = run("SELECT n FROM kusage WHERE uid=? AND day=?", (uid, today()), "one")
    free_left = max(0, FREE_DAILY - (row[0] if row else 0))
    return {"code": u["code"], "bonus": u["bonus"], "refs": u["refs"], "left": free_left + u["bonus"],
            "free_left": free_left, "free_limit": FREE_DAILY, "ref_bonus": REF_BONUS,
            "welcome_bonus": WELCOME_BONUS, "max_refs": MAX_REFS}


def join(uid, ref, ip):
    """Naya user banao aur (agar valid ho) referral bonus do. (me, credited) lautata hai."""
    if _user(uid):
        return me(uid), False
    h = ip_hash(ip)
    credited, ruid, bonus = False, None, 0
    ref = (ref or "").strip().upper()[:12]
    if ref:
        r = run("SELECT uid, refs, ip FROM kusers WHERE code=?", (ref,), "one")
        if r and r[0] != uid:
            ruid, refs, rip = r
            seen = run("SELECT 1 FROM krefs WHERE referrer=? AND ip=?", (ruid, h), "one")
            # same network/device se referral pe bonus nahi, ek IP se ek hi baar
            if refs < MAX_REFS and rip != h and not seen:
                credited, bonus = True, WELCOME_BONUS
    _create(uid, h, ruid if credited else None, bonus)
    if credited:
        run("UPDATE kusers SET bonus = bonus + ?, refs = refs + 1 WHERE uid=?", (REF_BONUS, ruid))
        try:
            run("INSERT INTO krefs (referrer, ip) VALUES (?,?)", (ruid, h))
        except Exception:
            pass
    return me(uid), credited


def consume(uid, ip):
    """1 message kharch karo. (ok, source, left) lautata hai."""
    if not _user(uid):
        _create(uid, ip_hash(ip))
    m = me(uid)
    if m["free_left"] > 0:
        run("INSERT INTO kusage (uid, day, n) VALUES (?,?,1) ON CONFLICT (uid, day) DO UPDATE SET n = kusage.n + 1",
            (uid, today()))
        return True, "free", m["left"] - 1
    if m["bonus"] > 0:
        run("UPDATE kusers SET bonus = bonus - 1 WHERE uid=? AND bonus > 0", (uid,))
        return True, "bonus", m["left"] - 1
    return False, None, 0


def refund(uid, source):
    if source == "free":
        run("UPDATE kusage SET n = n - 1 WHERE uid=? AND day=? AND n > 0", (uid, today()))
    elif source == "bonus":
        run("UPDATE kusers SET bonus = bonus + 1 WHERE uid=?", (uid,))
