import requests

BASE_URL = "http://127.0.0.1:5000/api"

# Step 1: Retrieve all users and pick one with role "homeless person"
users_url = f"{BASE_URL}/users"
response = requests.get(users_url)
if response.status_code != 200:
    print("Error retrieving users:", response.status_code, response.text)
    exit(1)

users = response.json()
user_id = None
for user in users:
    if user.get("role", "").strip().lower() == "homeless person":
        if user.get("name", "").strip().lower() == "test homeless":
            user_id = user["_id"]
            break

if not user_id:
    print("No user with role 'homeless person' found. Please create one first.")
    exit(1)

print("Using user with ID:", user_id)

# Step 2: Attempt to create a transaction to redeem (spend) 20 credits
txn_data = {
    "user": user_id,
    "type": "redeem",
    "amount": 5
}

create_txn_url = f"{BASE_URL}/transactions"
txn_response = requests.post(create_txn_url, json=txn_data)

if txn_response.status_code == 201:
    txn = txn_response.json()
    print("Transaction created successfully:")
    print(txn)
else:
    print("Error creating transaction:")
    print(txn_response.status_code, txn_response.text)
