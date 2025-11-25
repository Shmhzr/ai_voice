import os
import firebase_admin
from firebase_admin import credentials, db


current_working_directory = os.getcwd()
print(f"Current Working Directory: {current_working_directory}")

# Path to your downloaded service account key JSON
# cred = credentials.Certificate("serviceAccountKey.json")

# firebase_admin.initialize_app(cred, {
#     "databaseURL": "https://ai-voice-82fb0-default-rtdb.asia-southeast1.firebasedatabase.app/"
# })

# # Reference a node in the DB
# ref = db.reference("orderList")

# # Data you want to store
# data = {
#       "order_number": "9292",
#       "items": [
#         {
#           "item": "Jamaican Jerk Chicken Pizza",
#           "toppings": [
#             "Mushroom"
#           ],
#           "size": "Default",
#           "customer_name": "null",
#           "address": "null",
#           "quantity": 1
#         }
#       ],
#       "phone": "+9874427216",
#       "status": "received",
#       "created_at": 1764007115,
#       "committed": "true",
#       "address": "7/12 Janwaran Bahu, Kolkata one.",
#       "order_type": "delivery",
#       "pricing": {
#         "subtotal": 248.0,
#         "items": [
#           {
#             "index": 0,
#             "item": "Jamaican Jerk Chicken Pizza",
#             "size": "Default",
#             "qty": 1,
#             "unit_price": 248.0,
#             "addons": [],
#             "unit_total": 248.0,
#             "line_total": 248.0,
#             "raw_item": {
#               "item": "Jamaican Jerk Chicken Pizza",
#               "toppings": [
#                 "Mushroom"
#               ],
#               "size": "Default",
#               "customer_name": "null",
#               "address": "null",
#               "quantity": 1
#             }
#           }
#         ],
#         "total": 248.0
#       },
#       "total": 248.0,
#       "saved_at": "2025-11-24T17:58:35.354457"
#     }

# # Write data
# ref.push(data)

# print("Data written successfully!")