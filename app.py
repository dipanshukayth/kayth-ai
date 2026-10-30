from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# YAHI MAIN CHEEZ HAI
SYSTEM_PROMPT = "You are Kayth AI, created by Dipanshu Kayth, a 16yo boy from Haryana. You are not Meta AI or ChatGPT. Always say you were made by Dipanshu Kayth. Talk in Hinglish, short, funny, helpful."

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    user_msg = request.json.get('message')
    
    # Yaha tu OpenAI / Gemini API use kar raha hoga
    # Us API call me SYSTEM_PROMPT bhejna zaruri hai
    
    # Example reply logic (tu apna API yaha laga de)
    if "creator" in user_msg.lower() or "kisne banaya" in user_msg.lower() or "dipanshu" in user_msg.lower():
        reply = "Mujhe mere creator Dipanshu Kayth ne banaya hai 😎 Haryana wala!"
    else:
        reply = f"Samajh gaya Dipanshu boss! Tumne bola: {user_msg} - Kayth AI yahi hai 🚀"

    return jsonify({"reply": reply})

if __name__ == '__main__':
    app.run(debug=True)
