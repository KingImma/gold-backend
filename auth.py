import firebase_admin
from firebase_admin import auth, credentials
from fastapi import HTTPException, Header

cred = credentials.Certificate("goldbot-33101-firebase-adminsdk-fbsvc-d6ef46e273.json")
firebase_admin.initialize_app(cred)

def verify_firebase_token(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization Token")
    try:
        token = authorization.split(" ")[1]
        decoded_token = auth.verify_id_token(token)
        return decoded_token
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
