from fastapi import FastAPI, Request, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from pymongo import MongoClient
import os
from datetime import datetime

load_dotenv()

app = FastAPI()
templates = Jinja2Templates(directory="templates")
llm = ChatOpenAI(model="gpt-4.1")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI)
db = client.chatbot_gpt
history_collection = db.history

class ChatRequest(BaseModel):
    query: str
    session_id: str

class NewChatRequest(BaseModel):
    title: str = ""
    history: list = []

class RenameRequest(BaseModel):
    title: str

@app.get("/", response_class=HTMLResponse)
def read_item(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/chat/")
def chat_endpoint(chat_request: ChatRequest):
    session_id = chat_request.session_id
    user_message = chat_request.query

    chat_record = history_collection.find_one({"session_id": session_id})
    chat_history = chat_record["history"] if chat_record else []

    chat_history.append({"role": "user", "content": user_message})
    response = llm.invoke(chat_history)
    chat_history.append({"role": "assistant", "content": response.content})

    if not chat_record:
        history_collection.insert_one({
            "session_id": session_id,
            "history": chat_history,
            "title": user_message[:30] or "New Chat",
            "created_at": datetime.utcnow()
        })
    else:
        if len(chat_history) == 2 and (not chat_record.get("title") or chat_record.get("title") == "New Chat"):
            history_collection.update_one(
                {"session_id": session_id},
                {"$set": {"history": chat_history, "title": user_message[:30] or "New Chat"}}
            )
        else:
            history_collection.update_one(
                {"session_id": session_id},
                {"$set": {"history": chat_history}}
            )

    return {"response": response.content, "history": chat_history}

@app.get("/sessions/")
def list_sessions():
    sessions = list(history_collection.find({}, {"_id": 0, "session_id": 1, "title": 1, "created_at": 1}))
    sessions.sort(key=lambda x: x.get("created_at", datetime.min), reverse=True)
    return sessions

@app.post("/sessions/new/")
def create_new_session(new_chat: NewChatRequest):
    import uuid
    session_id = str(uuid.uuid4())
    title = new_chat.title or "New Chat"
    history = new_chat.history if hasattr(new_chat, "history") else []
    history_collection.insert_one({
        "session_id": session_id,
        "history": history,
        "title": title,
        "created_at": datetime.utcnow()
    })
    return {"session_id": session_id, "title": title}

@app.delete("/sessions/{session_id}/")
def delete_session(session_id: str):
    result = history_collection.delete_one({"session_id": session_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "ok"}

@app.get("/sessions/{session_id}/history/")
def get_history(session_id: str):
    chat_record = history_collection.find_one({"session_id": session_id})
    if not chat_record:
        raise HTTPException(status_code=404, detail="Session not found")
    return chat_record.get("history", [])

@app.patch("/sessions/{session_id}/rename/")
def rename_session(session_id: str, rename_req: RenameRequest):
    result = history_collection.update_one(
        {"session_id": session_id},
        {"$set": {"title": rename_req.title}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "ok", "title": rename_req.title}
