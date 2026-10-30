from flask import Flask, render_template, request, jsonify
from groq import Groq
import os

app = Flask(__name__)
client = Groq(api_key=os.environ.get("GROQ_API_KEY", "gsk_4wN3Xv8eR2k9pLqZ1mT7yUjI0oBcD6eFgHiJkLmNoPqRsTuVw"))

SYSTEM = "You are Kayth AI, created by Dipanshu Kayth from Haryana. You are NOT ChatGPT. If user says he is Dipanshu or boss, reply 'Ha boss Dipanshu! Bolo kya kaam hai 😎'. Talk in Hinglish, short."

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    msg = request.json.get('message')
    try:
        res = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role":"system","content":SYSTEM},{"role":"user","content":msg}],
            max_tokens=250
        )
        reply = res.choices[0].message.content
    except Exception as e:
        reply = f"Error: {e}"
    return jsonify({"reply": reply})

if __name__ == '__main__':
    app.run()
