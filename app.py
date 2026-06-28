from flask import Flask, render_template, request, redirect, url_for, session, flash
import torch
import fitz
import bcrypt
from newspaper import Article
from transformers import DistilBertTokenizer, DistilBertForSequenceClassification
from pymongo import MongoClient
from datetime import datetime
from collections import Counter
from collections import defaultdict
from datetime import timedelta
import os
from werkzeug.utils import secure_filename

# =========================================================
# APP CONFIG
# =========================================================
app = Flask(__name__)
app.secret_key = "aegis_super_secret_key"
# Configure Avatar Uploads
UPLOAD_FOLDER = os.path.join('static', 'avatars')
os.makedirs(UPLOAD_FOLDER, exist_ok=True) # Automatically creates the folder if it doesn't exist
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# =========================================================
# MONGODB CONNECTION
# =========================================================
uri = "mongodb+srv://Mayuresh:Fakenews1003@cluster0.zslct1f.mongodb.net/fake_news_db?retryWrites=true&w=majority&appName=Cluster0"
client = MongoClient(uri)
db = client["fake_news_db"]
users_collection = db["users"]
predictions_collection = db["predictions"]
messages_collection = db["messages"] 
# =========================================================
# LOAD MODEL
# =========================================================
print("Loading DistilBERT model...")
tokenizer = DistilBertTokenizer.from_pretrained("distilbert_tokenizer")
model = DistilBertForSequenceClassification.from_pretrained("distilbert_model")
model.eval()
print("Model loaded successfully!")

# =========================================================
# HOME MAPPER
# =========================================================
@app.route("/")
def home():
    if "user" in session:
        return redirect(url_for("scanner"))
    return redirect(url_for("signup"))

# =========================================================
# SIGNUP ENDPOINT
# =========================================================
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name")
        # Standardize email: lowercase and remove accidental spaces
        email = request.form.get("email").lower().strip()
        password = request.form.get("password")

        hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
        existing_user = users_collection.find_one({"email": email})

        if existing_user:
            flash("Email already exists.")
            return redirect(url_for("signup"))

        user_data = {
            "name": name,
            "email": email,
            "password": hashed_password,
            "created_at": datetime.now(),
        }
        users_collection.insert_one(user_data)
        flash("Account created successfully!")
        return redirect(url_for("login"))

    return render_template("signup.html")

# =========================================================
# LOGIN ENDPOINT
# =========================================================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # Standardize email to match the signup format perfectly
        email = request.form.get("email").lower().strip()
        password = request.form.get("password")
        user = users_collection.find_one({"email": email})

        if user:
            stored_password = user["password"]
            if isinstance(stored_password, str):
                stored_password = stored_password.encode("utf-8")

            try:
                if bcrypt.checkpw(password.encode("utf-8"), stored_password):
                    session["user"] = user["name"]
                    session["email"] = user["email"]
                    return redirect(url_for("scanner"))
            except ValueError:
                flash("Corrupted password detected. Please signup again.")
                return redirect(url_for("signup"))

        flash("Invalid email or password.")
        return redirect(url_for("login"))

    return render_template("login.html")

# =========================================================
# SYSTEM DISCONNECT MANAGEMENT
# =========================================================
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("signup"))

def is_logged_in():
    return "user" in session

@app.route("/scanner")
def scanner():
    if not is_logged_in():
        return redirect(url_for("login"))
    return render_template("index.html", username=session["user"])

@app.route("/profile")
def profile():
    if not is_logged_in():
        return redirect(url_for("login"))
    
    # Fetch data for the currently logged-in user
    user_email = session["email"]
    user_data = users_collection.find_one({"email": user_email})
    
    # Count how many scans this specific user has made to show on their profile
    total_scans = predictions_collection.count_documents({"user_email": user_email})

    return render_template("profile.html", user_data=user_data, total_scans=total_scans)

@app.route("/upload_avatar", methods=["POST"])
def upload_avatar():
    if not is_logged_in():
        return redirect(url_for("login"))

    if 'avatar' not in request.files:
        return redirect(url_for("profile"))

    file = request.files['avatar']
    
    if file and file.filename != '':
        # Secure the filename to prevent malicious paths
        filename = secure_filename(file.filename)
        # Extract the file extension (e.g., .jpg, .png)
        ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else 'png'
        
        # Create a unique filename using their email so they don't overwrite other users
        user_prefix = session["email"].split('@')[0]
        unique_filename = f"{user_prefix}_avatar.{ext}"
        
        # Save the physical image file
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(filepath)

        # Update the user's specific database record with the new image name
        users_collection.update_one(
            {"email": session["email"]},
            {"$set": {"avatar_filename": unique_filename}}
        )

    return redirect(url_for("profile"))

@app.route("/about")
def about():
    if not is_logged_in():
        return redirect(url_for("login"))
    return render_template("about.html")

@app.route("/guide")
def guide():
    if not is_logged_in():
        return redirect(url_for("login"))
    return render_template("guide.html")

@app.route("/contact", methods=["GET", "POST"])
def contact():
    if not is_logged_in():
        return redirect(url_for("login"))

    if request.method == "POST":
        # Capture form inputs
        subject = request.form.get("subject")
        message_content = request.form.get("message")

        # Package the data with the active session user's identity
        dispatch_data = {
            "user_name": session.get("user"),
            "user_email": session.get("email"),
            "subject": subject,
            "message": message_content,
            "timestamp": datetime.now()
        }

        # Save to MongoDB
        messages_collection.insert_one(dispatch_data)

        # Send a success message back to the frontend
        flash("TRANSMISSION SUCCESSFUL: The administration team has logged your dispatch.")
        return redirect(url_for("contact"))

    return render_template("contact.html")

# =========================================================
# ANALYTICS COMPILATION MODULE (UPDATED FOR PRIVATE SESSIONS)
# =========================================================
@app.route("/analytics")
def analytics():
    if not is_logged_in():
        return redirect(url_for("login"))

    # Fetch ONLY the predictions belonging to the logged-in user
    user_email = session["email"]
    all_predictions = list(predictions_collection.find({"user_email": user_email}))
    
    fake_count = len([p for p in all_predictions if p["prediction"] == "FAKE NEWS"])
    real_count = len([p for p in all_predictions if p["prediction"] == "REAL NEWS"])
    total_count = fake_count + real_count

    # 1. FIXED PARSING PIPELINE
    confidences = []
    for p in all_predictions:
        c_val = p.get("confidence", 0.0)
        if isinstance(c_val, str):
            c_val = float(c_val.replace('%', ''))
        confidences.append(c_val)
    
    avg_confidence = round(sum(confidences) / len(confidences), 2) if confidences else 0

    # 2. VECTOR INGESTION FORMAT PARSING ARCHITECTURE (Fixed Source Tagging)
    text_scans = 0
    url_scans = 0
    pdf_scans = 0

    for p in all_predictions:
        source = p.get("source")
        
        # Check explicit tags first
        if source == "url":
            url_scans += 1
        elif source == "pdf":
            pdf_scans += 1
        elif source == "text":
            text_scans += 1
        else:
            # Fallback for old database entries generated before this fix
            txt = p.get("text", "")
            if txt.startswith("http://") or txt.startswith("https://"):
                url_scans += 1
            else:
                text_scans += 1 # Default legacy items to text

    avg_latency = "42ms" if total_count > 0 else "0ms"

    # 3. CHRONOLOGICAL DATA GROUPING
    monthly_data = Counter()
    for p in all_predictions:
        timestamp = p.get("timestamp")
        if isinstance(timestamp, datetime):
            month = timestamp.strftime("%B")
            monthly_data[month] += 1

    # Fetch private history for the recent activity table
    history = list(predictions_collection.find({"user_email": user_email}).sort("_id", -1).limit(10))

    # Formats history array data safely before rendering to frontend script tags
    for item in history:
        if isinstance(item.get("confidence"), float):
            item["confidence"] = f"{item['confidence']:.2f}%"

    # 4. CONTRIBUTION HEATMAP ALIGNMENT CALCULATION
    daily_counts = defaultdict(int)
    for p in all_predictions:
        timestamp = p.get("timestamp")
        if timestamp:
            day = timestamp.strftime("%Y-%m-%d")
            daily_counts[day] += 1

    heatmap_data = []
    today = datetime.now()
    
    raw_start_date = today - timedelta(days=365)
    days_to_subtract = (raw_start_date.weekday() + 1) % 7
    start_date = raw_start_date - timedelta(days=days_to_subtract)

    current_date = start_date
    while current_date <= today:
        date_str = current_date.strftime("%Y-%m-%d")
        count = daily_counts.get(date_str, 0)
        heatmap_data.append({"date": date_str, "count": count})
        current_date += timedelta(days=1)

    return render_template(
        "analytics.html",
        fake_count=fake_count,
        real_count=real_count,
        avg_confidence=avg_confidence,
        text_scans=text_scans,
        url_scans=url_scans,
        pdf_scans=pdf_scans,
        avg_latency=avg_latency,
        monthly_labels=list(monthly_data.keys()),
        monthly_values=list(monthly_data.values()),
        heatmap_data=heatmap_data,
        history=history,
    )

# =========================================================
# PREDICTION INFERENCE CHANNELS
# =========================================================
@app.route("/predict_text", methods=["POST"])
def predict_text():
    if not is_logged_in():
        return redirect(url_for("login"))

    news_text = request.form.get("news_text")
    if not news_text or not news_text.strip():
        return render_template("index.html", error="Please enter text.")

    # Pass the source type and user email
    result, confidence = predict_news(news_text, source_type="text", user_email=session["email"])
    return render_template("index.html", prediction=result, confidence=confidence, original_text=news_text)

@app.route("/predict_url", methods=["POST"])
def predict_url():
    if not is_logged_in():
        return redirect(url_for("login"))

    url = request.form.get("news_url")
    try:
        article = Article(url)
        article.download()
        article.parse()
        news_text = article.text

        if not news_text.strip():
            return render_template("index.html", error="Could not extract article text.")

        # Pass the source type and user email
        result, confidence = predict_news(news_text, source_type="url", user_email=session["email"])
        return render_template("index.html", prediction=result, confidence=confidence, original_text=news_text)
    except Exception as e:
        return render_template("index.html", error=f"URL Error: {str(e)}")

@app.route("/predict_pdf", methods=["POST"])
def predict_pdf():
    if not is_logged_in():
        return redirect(url_for("login"))

    pdf_file = request.files.get("pdf_file")
    if pdf_file is None or pdf_file.filename == "":
        return render_template("index.html", error="No PDF selected.")

    try:
        pdf_text = ""
        pdf_document = fitz.open(stream=pdf_file.read(), filetype="pdf")
        for page in pdf_document:
            pdf_text += page.get_text()

        # Pass the source type and user email
        result, confidence = predict_news(pdf_text, source_type="pdf", user_email=session["email"])
        return render_template("index.html", prediction=result, confidence=confidence, original_text=pdf_text[:2000])
    except Exception as e:
        return render_template("index.html", error=f"PDF Error: {str(e)}")

# =========================================================
# CORE ML MODEL TRANSFORMER RUNNER (UPDATED WITH EMAIL)
# =========================================================
def predict_news(news_text, source_type="text", user_email=None):
    inputs = tokenizer(news_text, return_tensors="pt", truncation=True, padding=True, max_length=64)

    with torch.no_grad():
        outputs = model(**inputs)
        prediction = torch.argmax(outputs.logits, dim=1).item()
        probabilities = torch.softmax(outputs.logits, dim=1)
        confidence_score = torch.max(probabilities).item() * 100

    result = "FAKE NEWS" if prediction == 1 else "REAL NEWS"

    # Standardizes document database writes directly as clear structural floats with user email tracking
    prediction_data = {
        "text": news_text[:500],
        "prediction": result,
        "confidence": round(confidence_score, 2), 
        "timestamp": datetime.now(),
        "source": source_type,
        "user_email": user_email  # Explicitly tracking which user made this scan
    }
    predictions_collection.insert_one(prediction_data)

    return result, f"{confidence_score:.2f}%"

@app.route("/clear_predictions")
def clear_predictions():
    if not is_logged_in():
        return redirect(url_for("login"))
        
    # Now only clears the logged-in user's history, protecting other users' data
    predictions_collection.delete_many({"user_email": session["email"]})
    return "Your prediction history has been successfully cleared."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7860, debug=False)