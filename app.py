from flask import Flask, render_template, request, jsonify
import requests
import urllib.parse

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    user_msg = request.json.get('message')
    
    # System prompt + user msg
    full_prompt = f"You are Kayth AI, created by Dipanshu Kayth, 16yo from Haryana. You are NOT ChatGPT. If user says he is Dipanshu, say 'Ha boss Dipanshu! Bolo kya kaam hai 😎'. Talk in Hinglish, short, funny. User says: {user_msg}"
    
    try:
        # Free AI API - No key needed
        encoded = urllib.parse.quote(full_prompt)
        url = f"https://text.pollinations.ai/{encoded}"
        r = requests.get(url, timeout=15)
        reply = r.text
        if len(reply) > 500:
            reply = reply[:500]
    except Exception as e:
        reply = "Arey boss network slow hai, ek baar fir se bolo 😅"

    return jsonify({"reply": reply})

if __name__ == '__main__':
    app.run()
