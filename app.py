

import os
import json
import requests
from functools import wraps
from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from flask_restful import Resource, Api
from pymongo import MongoClient, errors
from bson.objectid import ObjectId
from google import genai

# Load environment variables
load_dotenv("config.env")

class Config:
    MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/EarnAndEat")
    DEBUG = os.environ.get("DEBUG", "False") == "True"

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "CHANGE_ME")
api = Api(app)

# Connect to MongoDB
try:
    client = MongoClient(app.config['MONGO_URI'])
    db = client.get_default_database()
except errors.ConnectionError as e:
    print("Error connecting to MongoDB:", e)
    exit(1)

# Pre-create necessary collections
for coll in ['users', 'opportunities', 'transactions', 'organizations', 'providers']:
    if coll not in db.list_collection_names():
        db.create_collection(coll)

users_collection = db['users']
opportunities_collection = db['opportunities']
transactions_collection = db['transactions']
organizations_collection = db['organizations']
providers_collection = db['providers']

def serialize_doc(doc):
    doc['_id'] = str(doc['_id'])
    return doc

# ------------------------------
# Initialize sample providers if none exist
# ------------------------------
if providers_collection.count_documents({}) == 0:
    sample_providers = [
        {"provider_name": "Sunny Shelter", "provider_type": "shelter", "available_quota": 100},
        {"provider_name": "Green Food Bank", "provider_type": "food bank", "available_quota": 200}
    ]
    providers_collection.insert_many(sample_providers)

# ------------------------------
# Gemini Chatbot Helper Function
# ------------------------------
gemini_api_key = os.environ.get("GEMINI_API_KEY", "YOUR_API_KEY")
gemini_client = genai.Client(api_key=gemini_api_key)

def get_ngo_info():
    ngos = list(users_collection.find({"role": "ngo"}))
    ngos_info = []
    for ngo in ngos:
        ngo = serialize_doc(ngo)
        cause = ngo.get("cause", "No cause provided")
        ngos_info.append(f"{ngo['name']} ({cause})")
    return ", ".join(ngos_info)

def eat_and_earn_chat(user_question):
    ngo_info = get_ngo_info()
    background = f"""
    You are the Eat & Earn assistant.
    The Eat & Earn program awards credits to homeless people for volunteering and allows them to redeem these credits at credit-based food banks or shelters.
    NGOs organize volunteering opportunities, and homeless people can earn credits by volunteering.
    Current NGOs in the system: {ngo_info}.
    Always answer in a helpful and structured way, referencing Eat & Earn processes.
    """
    full_prompt = f"{background}\nUser: {user_question}\nAssistant:"
    response = gemini_client.models.generate_content(
        model="gemini-2.0-flash",
        contents=full_prompt
    )
    return response.text

# ------------------------------
# Decorators
# ------------------------------
def requires_login(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('sign_in'))
        return f(*args, **kwargs)
    return decorated_function

# ------------------------------
# Local Auth Routes
# ------------------------------
@app.route('/')
def home_page():
    return render_template('index.html')

@app.route('/sign_in', methods=['GET', 'POST'])
def sign_in():
    if request.method == 'GET':
        return render_template('sign_in.html')
    else:
        email = request.form.get('email')
        password = request.form.get('password')
        # Check in users collection (NGO and normal user)
        user = users_collection.find_one({"email": email, "password": password})
        if user:
            session['user_id'] = str(user['_id'])
            session['role'] = user.get('role', '').lower()
            if session['role'] == 'ngo':
                return redirect(url_for('web_ngo_dashboard'))
            else:
                return redirect(url_for('list_ngos_for_user'))
        else:
            # Check if organization
            org = organizations_collection.find_one({"email": email, "password": password})
            if org:
                session['user_id'] = str(org['_id'])
                session['role'] = "organization"
                return redirect(url_for('org_manage_page'))
            return "Invalid credentials. <a href='/sign_in'>Try again</a>"

@app.route('/sign_up', methods=['GET', 'POST'])
def sign_up():
    if request.method == 'GET':
        return render_template('sign_up.html')
    else:
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role', 'user').lower()
        new_user = {"name": name, "email": email, "password": password, "role": role}
        if role == 'ngo':
            cause = request.form.get('cause')  # 3-4 word description of their cause
            new_user['cause'] = cause
        if users_collection.find_one({"email": email}):
            return "User with that email already exists. <a href='/sign_in'>Sign in instead</a>"
        result = users_collection.insert_one(new_user)
        session['user_id'] = str(result.inserted_id)
        session['role'] = role
        if role == 'ngo':
            return redirect(url_for('web_ngo_dashboard'))
        else:
            return redirect(url_for('list_ngos_for_user'))

@app.route('/enroll_org', methods=['GET', 'POST'])
def enroll_org():
    if request.method == 'GET':
        return render_template('org_sign_up.html')
    else:
        org_name = request.form.get('org_name')
        email = request.form.get('email')
        password = request.form.get('password')
        if organizations_collection.find_one({"email": email}):
            return "Organization with that email already exists. <a href='/sign_in'>Sign in instead</a>"
        new_org = {
            "org_name": org_name,
            "email": email,
            "password": password,
            "events": []
        }
        result = organizations_collection.insert_one(new_org)
        session['user_id'] = str(result.inserted_id)
        session['role'] = "organization"
        return redirect(url_for('org_manage_page'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home_page'))

# ------------------------------
# NGO Routes
# ------------------------------
@app.route('/web/ngo/dashboard', methods=['GET'])
@requires_login
def web_ngo_dashboard():
    if session['role'] != 'ngo':
        return "Access denied. Only NGOs allowed."
    ngo_id = session['user_id']
    homeless = list(users_collection.find({"role": "homeless person", "added_by": ngo_id}))
    homeless = [serialize_doc(u) for u in homeless]
    return render_template('ngo_dashboard.html', homeless=homeless)

@app.route('/web/ngo/add-homeless', methods=['GET', 'POST'])
@requires_login
def web_ngo_add_homeless():
    if session['role'] != 'ngo':
        return "Access denied. Only NGOs allowed."
    if request.method == 'GET':
        return render_template('add_homeless.html')
    else:
        name = request.form.get('name')
        email = request.form.get('email')
        shelter_credits = int(request.form.get('shelter_credits', 0))
        food_credits = int(request.form.get('food_credits', 0))
        added_by = session['user_id']
        homeless_data = {
            "name": name,
            "email": email,
            "role": "homeless person",
            "shelter_credits": shelter_credits,
            "food_credits": food_credits,
            "added_by": added_by
        }
        users_collection.insert_one(homeless_data)
        return redirect(url_for('web_ngo_dashboard'))

# NGO assigns a homeless person to an organization's event.
@app.route('/web/ngo/assign_org', methods=['GET', 'POST'])
@requires_login
def assign_org():
    if session['role'] != 'ngo':
        return "Access denied. Only NGOs can assign volunteers."
    if request.method == 'GET':
        ngo_id = session['user_id']
        homeless_list = list(users_collection.find({"role": "homeless person", "added_by": ngo_id}))
        homeless_list = [serialize_doc(h) for h in homeless_list]
        events = []
        for org in organizations_collection.find():
            org = serialize_doc(org)
            if "events" in org:
                for idx, event in enumerate(org["events"]):
                    if event.get("positions_available", 0) > 0:
                        event["org_id"] = org["_id"]
                        event["org_name"] = org.get("org_name", "Unnamed Organization")
                        event["event_index"] = idx
                        events.append(event)
        return render_template('assign_org.html', homeless_list=homeless_list, events=events)
    else:
        homeless_id = request.form.get('homeless_id')
        selected = request.form.get('selected_event')
        try:
            org_id, event_index = selected.split("|")
            event_index = int(event_index)
        except Exception:
            return "Invalid event selection.", 400
        org = organizations_collection.find_one({"_id": ObjectId(org_id)})
        if not org:
            return "Organization not found.", 404
        if "events" not in org or len(org["events"]) <= event_index:
            return "Event not found.", 404
        event = org["events"][event_index]
        if event.get("positions_available", 0) <= 0:
            return "No positions available in that event.", 400
        new_positions = event["positions_available"] - 1
        organizations_collection.update_one(
            {"_id": ObjectId(org_id)},
            {"$set": {f"events.{event_index}.positions_available": new_positions}}
        )
        users_collection.update_one(
            {"_id": ObjectId(homeless_id)},
            {"$set": {
                "org_assigned": org.get("org_name", "Unnamed Organization"),
                "event_assigned": event.get("eventName", "Unnamed Event"),
                "org_assigned_id": org_id,
                "event_index": event_index,
                "event_completed": False
            }}
        )
        return redirect(url_for('web_ngo_dashboard'))

# NGO marks an event as done for a homeless person.
@app.route('/web/ngo/mark_event_done', methods=['POST'])
@requires_login
def mark_event_done():
    if session['role'] != 'ngo':
        return "Access denied. Only NGOs can mark events as done."
    homeless_id = request.form.get('homeless_id')
    org_id = request.form.get('org_id')
    event_index = int(request.form.get('event_index', -1))
    org = organizations_collection.find_one({"_id": ObjectId(org_id)})
    if not org or "events" not in org or len(org["events"]) <= event_index:
        return "Event not found.", 404
    event = org["events"][event_index]
    shelter_offered = event.get("shelter_credits_offered", 0)
    food_offered = event.get("food_credits_offered", 0)
    users_collection.update_one(
        {"_id": ObjectId(homeless_id)},
        {
            "$inc": {"shelter_credits": shelter_offered, "food_credits": food_offered},
            "$set": {"event_completed": True}
        }
    )
    return redirect(url_for('web_ngo_dashboard'))

# ------------------------------
# Normal User Routes
# ------------------------------
@app.route('/web/user/ngos', methods=['GET'])
@requires_login
def list_ngos_for_user():
    if session['role'] in ['ngo', 'organization']:
        return "Access denied. Only normal users allowed."
    ngos = list(users_collection.find({"role": "ngo"}))
    ngos = [serialize_doc(n) for n in ngos]
    return render_template('list_ngos.html', ngos=ngos)

# ------------------------------
# Organization Management
# ------------------------------
@app.route('/org/manage', methods=['GET', 'POST'])
@requires_login
def org_manage_page():
    if session['role'] != 'organization':
        return "Access denied. Only organizations allowed."
    org_id = session['user_id']
    org = organizations_collection.find_one({"_id": ObjectId(org_id)})
    if not org:
        return "Organization not found."
    org = serialize_doc(org)
    if request.method == 'POST':
        event_name = request.form.get('eventName')
        positions_available = int(request.form.get('positions_available', 0))
        shelter_offered = int(request.form.get('shelter_offered', 0))
        food_offered = int(request.form.get('food_offered', 0))
        new_event = {
            "eventName": event_name,
            "positions_available": positions_available,
            "shelter_credits_offered": shelter_offered,
            "food_credits_offered": food_offered
        }
        organizations_collection.update_one(
            {"_id": ObjectId(org_id)},
            {"$push": {"events": new_event}}
        )
        org = organizations_collection.find_one({"_id": ObjectId(org_id)})
        org = serialize_doc(org)
    return render_template('org_dashboard.html', org=org)

# ------------------------------
# Opportunities
# ------------------------------
@app.route('/web/opportunities', methods=['GET'])
def web_opportunities():
    opps = list(opportunities_collection.find())
    opps = [serialize_doc(o) for o in opps]
    return render_template('opportunities.html', opportunities=opps)

@app.route('/web/opportunities/create', methods=['POST'])
@requires_login
def web_opportunities_create():
    title = request.form.get('title')
    description = request.form.get('description', '')
    opp_data = {"title": title, "description": description}
    opportunities_collection.insert_one(opp_data)
    return redirect(url_for('web_opportunities'))

@app.route('/web/opportunities/delete/<string:opp_id>', methods=['GET'])
@requires_login
def web_opportunities_delete(opp_id):
    opportunities_collection.delete_one({"_id": ObjectId(opp_id)})
    return redirect(url_for('web_opportunities'))


# ------------------------------
# NGO-Assisted Homeless Redemption
# ------------------------------
@app.route('/web/homeless/redeem', methods=['GET', 'POST'])
@requires_login
def homeless_redeem():
    # Only allow access for NGOs
    if session['role'] != 'ngo':
        return "Access denied. Only NGOs can perform redemption on behalf of homeless persons."
    
    if request.method == 'GET':
        # List available providers (shelters and food banks)
        providers = list(providers_collection.find())
        providers = [serialize_doc(p) for p in providers]
        # Also list homeless persons added by the NGO for whom redemption can be processed
        ngo_id = session['user_id']
        homeless_list = list(users_collection.find({"role": "homeless person", "added_by": ngo_id}))
        homeless_list = [serialize_doc(h) for h in homeless_list]
        return render_template('homeless_redeem.html', providers=providers, homeless_list=homeless_list)
    
    else:
        provider_id = request.form.get('provider_id')
        redeem_amount = int(request.form.get('amount', 0))
        homeless_id = request.form.get('homeless_id')
        # Retrieve homeless record
        homeless = users_collection.find_one({"_id": ObjectId(homeless_id)})
        if not homeless:
            return "Homeless record not found.", 404
        # Retrieve provider record
        provider = providers_collection.find_one({"_id": ObjectId(provider_id)})
        if not provider:
            return "Provider not found.", 404
        provider_type = provider.get("provider_type", "").lower()
        if provider_type == "shelter":
            credit_type = "shelter"
        elif provider_type == "food bank":
            credit_type = "food"
        else:
            return "Invalid provider type.", 400
        current_credits = homeless.get(f"{credit_type}_credits", 0)
        if current_credits < redeem_amount:
            return "Not enough credits to redeem.", 400
        # Deduct credits from homeless person
        users_collection.update_one({"_id": ObjectId(homeless_id)}, {"$inc": {f"{credit_type}_credits": -redeem_amount}})
        # Deduct from provider's available quota
        providers_collection.update_one({"_id": ObjectId(provider_id)}, {"$inc": {"available_quota": -redeem_amount}})
        return redirect(url_for('homeless_redeem_confirmation'))

@app.route('/web/homeless/redeem/confirmation', methods=['GET'])
@requires_login
def homeless_redeem_confirmation():
    # Only NGOs can see the confirmation page
    if session['role'] != 'ngo':
        return "Access denied."
    return render_template('homeless_redeem_confirmation.html')


# ------------------------------
# Gemini Chatbot Endpoints with Eat & Earn Context
# ------------------------------
def eat_and_earn_chat(user_question):
    ngo_info = get_ngo_info()
    background = f"""
    You are the Eat & Earn assistant.
    The Eat & Earn program awards credits to homeless people for volunteering and allows them to redeem these credits at credit-based food banks or shelters.
    NGOs organize volunteering opportunities, and homeless people can earn credits by volunteering.
    Current NGOs in the system: {ngo_info}.
    Always answer in a helpful and structured way, referencing Eat & Earn processes.
    """
    full_prompt = f"{background}\nUser: {user_question}\nAssistant:"    
    response = gemini_client.models.generate_content(
        model="gemini-2.0-flash",
        contents=full_prompt
    )
    return response.text

@app.route('/web/gemini/chat', methods=['GET'])
def gemini_chat_page():
    return render_template('gemini_chat.html')

@app.route('/web/gemini/chat', methods=['POST'])
def gemini_chat():
    data = request.get_json()
    prompt = data.get("prompt", "")
    if not prompt:
        return jsonify({"response": "No prompt provided"}), 400
    answer = eat_and_earn_chat(prompt)
    return jsonify({"response": answer})

# ------------------------------
# Transaction Logic
# ------------------------------
def update_user_credits(user_id, amount, txn_type, credit_type):
    user = users_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        return False, "User not found"
    if user.get("role", "").strip().lower() != "homeless person":
        return False, "Transactions can only be applied to homeless persons"
    if credit_type not in ["shelter", "food"]:
        return False, "Invalid credit type. Must be 'shelter' or 'food'."
    field = f"{credit_type}_credits"
    current_credits = user.get(field, 0)
    if txn_type == "earn":
        new_balance = current_credits + amount
    elif txn_type == "redeem":
        if current_credits < amount:
            return False, "Insufficient credits"
        new_balance = current_credits - amount
    else:
        return False, "Invalid transaction type"
    users_collection.update_one({"_id": ObjectId(user_id)}, {"$set": {field: new_balance}})
    return True, new_balance

class TransactionList(Resource):
    def get(self):
        txns = list(transactions_collection.find())
        return jsonify([serialize_doc(txn) for txn in txns])
    
    def post(self):
        data = request.get_json()
        required_fields = ["user", "type", "amount", "credit_type", "actor_role"]
        for field in required_fields:
            if field not in data:
                return {"error": f"Missing field: {field}"}, 400
        user_id = data["user"]
        txn_type = data["type"]
        try:
            amount = int(data["amount"])
        except ValueError:
            return {"error": "Amount must be an integer"}, 400
        credit_type = data["credit_type"]
        actor_role = data["actor_role"].strip().lower()
        if txn_type == "earn" and actor_role != "volunteering workplace":
            return {"error": "Only volunteering workplace can trigger earn transactions"}, 400
        if txn_type == "redeem" and actor_role not in ["credit based food bank", "credit based shelter"]:
            return {"error": "Only credit based food banks or shelters can trigger redeem transactions"}, 400
        success, result_val = update_user_credits(user_id, amount, txn_type, credit_type)
        if not success:
            return {"error": result_val}, 400
        result = transactions_collection.insert_one(data)
        new_txn = transactions_collection.find_one({"_id": result.inserted_id})
        return serialize_doc(new_txn), 201

class Transaction(Resource):
    def get(self, txn_id):
        txn = transactions_collection.find_one({"_id": ObjectId(txn_id)})
        if txn:
            return serialize_doc(txn)
        return {"error": "Transaction not found"}, 404

    def put(self, txn_id):
        data = request.get_json()
        result = transactions_collection.update_one({"_id": ObjectId(txn_id)}, {"$set": data})
        if result.matched_count == 0:
            return {"error": "Transaction not found"}, 404
        txn = transactions_collection.find_one({"_id": ObjectId(txn_id)})
        return serialize_doc(txn)

    def delete(self, txn_id):
        result = transactions_collection.delete_one({"_id": ObjectId(txn_id)})
        if result.deleted_count == 0:
            return {"error": "Transaction not found"}, 404
        return {"message": "Transaction deleted successfully"}

api.add_resource(TransactionList, '/api/transactions')
api.add_resource(Transaction, '/api/transactions/<string:txn_id>')

if __name__ == '__main__':
    app.run(debug=app.config['DEBUG'], use_reloader=False)
