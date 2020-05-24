import sqlite3
import requests

from flask import Flask, flash, jsonify, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime
from helpers import *

# Configure application
application = app = Flask(__name__)

# Ensure templates are auto-reloaded
application.config["TEMPLATES_AUTO_RELOAD"] = True

# Configure session to use filesystem (instead of signed cookies)
application.config["SESSION_FILE_DIR"] = mkdtemp()
application.config["SESSION_PERMANENT"] = False
application.config["SESSION_TYPE"] = "filesystem"
Session(application)

# Load config.py
application.config.from_object("config")

# connecting to the database  
connection = sqlite3.connect("deepai.db", check_same_thread=False) 
db = connection.cursor() 

# Ensure responses aren't cached
@application.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response
    
# Upload to S3
def upload_file_to_s3(file, bucket_name, acl="public-read"):

    try:

        s3.upload_fileobj(
            file,
            bucket_name,
            file.filename,
            ExtraArgs={
                "ACL": acl,
                "ContentType": file.content_type
            }
        )

    except Exception as e:
        # This is a catch all exception, edit this part to fit your needs.
        print("Something Happened: ", e)
        return e
    
    return "{}{}".format(app.config["S3_LOCATION"], file.filename)

@application.route("/")
def index():
    return render_template("index.html")

@application.route("/colorize", methods=["GET", "POST"])
def colorize():
    if request.method == "GET":
        return render_template("colorize.html")
    else:
        
        submit = request.form.get("submit-button")
        if submit == "random":
            img = requests.get('https://source.unsplash.com/featured/?black%20and%20white', allow_redirects=False).headers['Location']
    
        if submit == "url":
            img = request.form.get("image-url")
            if not img:
                error = "Must enter a URL."
                return render_template("colorize.html", error=error)
                
        if submit == "upload":
            if "user_file" not in request.files:
                error = "No 'user_file' key in request.files"
                return render_template("colorize.html", error=error)
            else:
                file = request.files["user_file"]
                if file and allowed_file(file.filename):
                    file.filename   = secure_filename(file.filename)
                    output          = upload_file_to_s3(file, app.config["S3_BUCKET"])
                    img             = str(output)
                else:
                    return render_template("colorize.html", error="Something happened.")
        
        # Ping the DeepAI API
        
        response = requests.post(
            "https://api.deepai.org/api/colorizer",
            data={
                'image': img,
            },
            headers={'api-key': deepaikey}
        )
        
        colorized_img = response.json()['output_url']
    
        return render_template("colorize.html", img=img, colorized_img=colorized_img)


@application.route("/caption", methods=["GET", "POST"])
def caption():
    if request.method == "GET":
        return render_template("caption.html")
    else:
        
        submit = request.form.get("submit-button")
        if submit == "random":
            img = requests.get('https://source.unsplash.com/random/1200x800', allow_redirects=False).headers['Location']
    
        if submit == "url":
            img = request.form.get("image-url")
            if not img:
                error = "Must enter a URL."
                return render_template("caption.html", error=error)
                
        if submit == "upload":
            if "user_file" not in request.files:
                error = "No 'user_file' key in request.files"
                return render_template("caption.html", error=error)
            else:
                file = request.files["user_file"]
                if file and allowed_file(file.filename):
                    file.filename   = secure_filename(file.filename)
                    output          = upload_file_to_s3(file, app.config["S3_BUCKET"])
                    img             = str(output)
                else:
                    return render_template("caption.html", error="Something happened.")
        
        # Ping the DeepAI API
        
        response = requests.post(
            "https://api.deepai.org/api/neuraltalk",
            data = {'image': img},
            headers = {'api-key': deepaikey}
        )
    
        caption = response.json()['output'].capitalize()
    
        return render_template("caption.html", img=img, caption=caption)
    
@application.route("/logout")
def logout():
    
    session.clear()
    return redirect("/")

@application.route("/login", methods=["GET", "POST"])
def login():
    
    # Forget any user id
    session.clear()
    
    if request.method == "GET":
        return render_template("login.html")
    else:
        
        # Ensure email was submitted
        email = request.form.get("email")
        if not email:
            return render_template("login.html", error = "Must enter an email")
        
        # Ensure password was submitted
        password = request.form.get("password")
        if not password:
            return render_template("login.html", error = "Must enter password.")
        
        # Query database for username
        db.execute("SELECT * FROM users WHERE email=:email", {"email": email})
        rows = db.fetchall()
        
        # Check username and password are correct
        if len(rows) != 1 or not check_password_hash(rows[0][3], password):
            return render_template("login.html", error = "Invalid username and/or password")
        
        # Remember which user has logged in
        session["user_id"] = rows[0][0]
        
        # Redirect to homepage
        return redirect("/")

@application.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")
    else:
        
        # Check name
        name = request.form.get("name")
        if not name:
            return render_template("register.html", error = "Must enter a name.")
        
        # Check email
        email = request.form.get("email")
        if not email:
            return render_template("register.html", error = "Must enter an email.")
        
        # Check if email already exists
        db.execute("SELECT * FROM users WHERE email=:email", {"email": email})
        rows = db.fetchall()
        if len(rows) != 0:
            return render_template("register.html", error = "Email already exists.")
        
        # Check password
        password = request.form.get("password")
        if not password:
            return render_template("register.html", error = "Must enter a password.")
        confirmation = request.form.get("confirmation")
        if not confirmation:
            return render_template("register.html", error = "Must confirm your password.")
        elif password != confirmation:
            return render_template("register.html", error = "Passwords do not match.")
        
        # Hash password
        hash = generate_password_hash(password)
        
        # Creat user
        db.execute("INSERT INTO users (name, email, hash) VALUES (:name, :email, :hash)", {"name": name, "email": email, "hash": hash})
        connection.commit()
        
        # Remember which user has logged in
        # -- Get user id
        db.execute("SELECT user_id FROM users WHERE email=:email", {"email": email})
        rows = db.fetchall()
        print(rows)
        session["user_id"] = rows[0][0]
        
        return redirect("/")
        
    return render_template("register.html")
    

# Close sqlite connection
# connection.close()