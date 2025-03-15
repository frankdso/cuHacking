import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_restful import Resource, Api
from pymongo import MongoClient, errors
from bson.objectid import ObjectId

# Load environment variables from .env file
load_dotenv("config.env")

# Configuration using a Config class
class Config:
    # Try to get MONGO_URI from the .env file; otherwise, default to a local MongoDB instance
    MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/EarnAndEat")
    DEBUG = os.environ.get("DEBUG", "False") == "True"

app = Flask(__name__)
app.config.from_object(Config)
api = Api(app)

# Connect to MongoDB using the URI from the config
try:
    client = MongoClient(app.config['MONGO_URI'])
    # This will select the database specified in the URI (or you can specify one here)
    db = client.get_default_database()
except errors.ConnectionError as e:
    print("Error connecting to MongoDB:", e)
    exit(1)

# Explicitly create collections if they don't exist (MongoDB creates them on first write, too)
existing_collections = db.list_collection_names()
if 'users' not in existing_collections:
    db.create_collection('users')
if 'opportunities' not in existing_collections:
    db.create_collection('opportunities')
if 'transactions' not in existing_collections:
    db.create_collection('transactions')

# Define collections
users_collection = db['users']
opportunities_collection = db['opportunities']
transactions_collection = db['transactions']

def serialize_doc(doc):
    """Convert MongoDB document ObjectId to string for JSON serialization."""
    doc['_id'] = str(doc['_id'])
    return doc

# --------------------------
# User Resources
# --------------------------
class UserList(Resource):
    def get(self):
        """Retrieve all users."""
        users = list(users_collection.find())
        return jsonify([serialize_doc(user) for user in users])

    def post(self):
        """Create a new user."""
        data = request.get_json()
        result = users_collection.insert_one(data)
        new_user = users_collection.find_one({"_id": result.inserted_id})
        return serialize_doc(new_user), 201

class User(Resource):
    def get(self, user_id):
        """Retrieve a single user by ID."""
        try:
            user = users_collection.find_one({"_id": ObjectId(user_id)})
            if user:
                return serialize_doc(user)
            return {"error": "User not found"}, 404
        except Exception as e:
            return {"error": str(e)}, 400

    def put(self, user_id):
        """Update a user by ID."""
        data = request.get_json()
        try:
            result = users_collection.update_one({"_id": ObjectId(user_id)}, {"$set": data})
            if result.matched_count == 0:
                return {"error": "User not found"}, 404
            user = users_collection.find_one({"_id": ObjectId(user_id)})
            return serialize_doc(user)
        except Exception as e:
            return {"error": str(e)}, 400

    def delete(self, user_id):
        """Delete a user by ID."""
        try:
            result = users_collection.delete_one({"_id": ObjectId(user_id)})
            if result.deleted_count == 0:
                return {"error": "User not found"}, 404
            return {"message": "User deleted successfully"}
        except Exception as e:
            return {"error": str(e)}, 400

# --------------------------
# Opportunity Resources
# --------------------------
class OpportunityList(Resource):
    def get(self):
        """Retrieve all opportunities."""
        opps = list(opportunities_collection.find())
        return jsonify([serialize_doc(opp) for opp in opps])

    def post(self):
        """Create a new opportunity."""
        data = request.get_json()
        result = opportunities_collection.insert_one(data)
        new_opp = opportunities_collection.find_one({"_id": result.inserted_id})
        return serialize_doc(new_opp), 201

class Opportunity(Resource):
    def get(self, opp_id):
        """Retrieve a single opportunity by ID."""
        try:
            opp = opportunities_collection.find_one({"_id": ObjectId(opp_id)})
            if opp:
                return serialize_doc(opp)
            return {"error": "Opportunity not found"}, 404
        except Exception as e:
            return {"error": str(e)}, 400

    def put(self, opp_id):
        """Update an opportunity by ID."""
        data = request.get_json()
        try:
            result = opportunities_collection.update_one({"_id": ObjectId(opp_id)}, {"$set": data})
            if result.matched_count == 0:
                return {"error": "Opportunity not found"}, 404
            opp = opportunities_collection.find_one({"_id": ObjectId(opp_id)})
            return serialize_doc(opp)
        except Exception as e:
            return {"error": str(e)}, 400

    def delete(self, opp_id):
        """Delete an opportunity by ID."""
        try:
            result = opportunities_collection.delete_one({"_id": ObjectId(opp_id)})
            if result.deleted_count == 0:
                return {"error": "Opportunity not found"}, 404
            return {"message": "Opportunity deleted successfully"}
        except Exception as e:
            return {"error": str(e)}, 400

# Helper function to update user's credits with role check
def update_user_credits(user_id, amount, txn_type):
    try:
        user = users_collection.find_one({"_id": ObjectId(user_id)})
        if not user:
            return False, "User not found"
        
        # Only allow transactions for users with role "HomeLess person"
        if user.get("role", "").strip().lower() != "homeless person":
            return False, "User type not allowed to perform transactions"
        
        current_credits = user.get("credits", 0)
        if txn_type == "redeem" and current_credits < amount:
            return False, "Insufficient credits"
        
        new_balance = current_credits + amount if txn_type == "earn" else current_credits - amount
        users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"credits": new_balance}}
        )
        return True, new_balance
    except Exception as e:
        return False, str(e)

# --------------------------
# Transaction Resources with Credit Logic and Role Check
# --------------------------
class TransactionList(Resource):
    def get(self):
        """Retrieve all transactions."""
        txns = list(transactions_collection.find())
        return jsonify([serialize_doc(txn) for txn in txns])

    def post(self):
        """Create a new transaction and update user's credit balance if allowed."""
        data = request.get_json()

        # Validate required fields for transaction
        required_fields = ["user", "type", "amount"]
        for field in required_fields:
            if field not in data:
                return {"error": f"Missing field: {field}"}, 400

        # Extract values
        user_id = data["user"]
        txn_type = data["type"]
        try:
            amount = int(data["amount"])
        except ValueError:
            return {"error": "Amount must be an integer"}, 400

        # Validate transaction type
        if txn_type not in ["earn", "redeem"]:
            return {"error": "Transaction type must be either 'earn' or 'redeem'"}, 400

        # Update the user's credits before recording the transaction
        success, result_val = update_user_credits(user_id, amount, txn_type)
        if not success:
            return {"error": result_val}, 400

        # Insert the transaction record
        result = transactions_collection.insert_one(data)
        new_txn = transactions_collection.find_one({"_id": result.inserted_id})
        return serialize_doc(new_txn), 201


class Transaction(Resource):
    def get(self, txn_id):
        """Retrieve a single transaction by ID."""
        try:
            txn = transactions_collection.find_one({"_id": ObjectId(txn_id)})
            if txn:
                return serialize_doc(txn)
            return {"error": "Transaction not found"}, 404
        except Exception as e:
            return {"error": str(e)}, 400

    def put(self, txn_id):
        """Update a transaction by ID."""
        data = request.get_json()
        try:
            result = transactions_collection.update_one({"_id": ObjectId(txn_id)}, {"$set": data})
            if result.matched_count == 0:
                return {"error": "Transaction not found"}, 404
            txn = transactions_collection.find_one({"_id": ObjectId(txn_id)})
            return serialize_doc(txn)
        except Exception as e:
            return {"error": str(e)}, 400

    def delete(self, txn_id):
        """Delete a transaction by ID."""
        try:
            result = transactions_collection.delete_one({"_id": ObjectId(txn_id)})
            if result.deleted_count == 0:
                return {"error": "Transaction not found"}, 404
            return {"message": "Transaction deleted successfully"}
        except Exception as e:
            return {"error": str(e)}, 400
        


@app.route('/')
def home():
    return "Welcome to the Earn & Eat API"

# --------------------------
# API Endpoint Registration
# --------------------------
api.add_resource(UserList, '/api/users')
api.add_resource(User, '/api/users/<string:user_id>')
api.add_resource(OpportunityList, '/api/opportunities')
api.add_resource(Opportunity, '/api/opportunities/<string:opp_id>')
api.add_resource(TransactionList, '/api/transactions')
api.add_resource(Transaction, '/api/transactions/<string:txn_id>')

if __name__ == '__main__':
    app.run(debug=app.config['DEBUG'], use_reloader=False)

