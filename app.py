from flask import Flask, render_template, request, jsonify
from g4f.client import Client

app = Flask(__name__)
client = Client()

SYSTEM_PROMPT = "You are Kayth AI, created by Dipanshu Kayth, 16yo from Haryana. You are NOT ChatGPT or Meta AI. If someone says he is Dipanshu, reply 'Ha boss Dipanshu! Bolo kya kaam hai 😎'. Talk in Hinglish, short, funny, 1 emoji max."

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    user_msg = request.json.get('message')
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg}
            ],
        )
        reply = response.choices[0].message.content
    except:
        reply = "Arey thoda load hai boss, fir se puch 😅"

    return jsonify({"reply": reply})

if __name__ == '__main__':
    app.run()
