"""
Klleon Avatar Persona API Server
- 페르소나 프롬프트를 SQLite에 저장하고 REST API로 제공
- Android 앱: GET /api/persona  (앱 시작 시 1회 조회)
- 웹 관리자:  GET/PUT /api/persona, GET /api/persona/history
"""

import sqlite3
import secrets
import os
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

# ─── 설정 ──────────────────────────────────────────────────────────────────────
DB_PATH = os.environ.get("DB_PATH", "persona.db")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "klleon-admin-2024")  # 운영 시 반드시 변경

DEFAULT_PROMPT = """당신은 Klleon이 만든 AI 아바타 어시스턴트입니다.
친절하고 전문적인 태도로 사용자의 질문에 답변합니다.
답변은 간결하고 명확하게 2~3문장 이내로 작성합니다.
한국어로 질문받으면 한국어로, 영어로 질문받으면 영어로, 일본어로 질문받으면 일본어로 답변합니다."""

# ─── FastAPI 앱 ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Klleon Persona API",
    description="아바타 페르소나 프롬프트 관리 API",
    version="1.0.0"
)

# CORS 설정 (웹 페이지 → API 호출 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── 데이터베이스 초기화 ────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """DB 테이블 생성 및 기본 프롬프트 삽입"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 현재 활성 프롬프트 테이블
    cur.execute("""
        CREATE TABLE IF NOT EXISTS persona (
            id INTEGER PRIMARY KEY,
            prompt TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by TEXT DEFAULT 'admin'
        )
    """)

    # 변경 이력 테이블
    cur.execute("""
        CREATE TABLE IF NOT EXISTS persona_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prompt TEXT NOT NULL,
            saved_at TEXT NOT NULL,
            saved_by TEXT DEFAULT 'admin',
            note TEXT
        )
    """)

    # 기본 프롬프트가 없으면 삽입
    cur.execute("SELECT COUNT(*) FROM persona")
    if cur.fetchone()[0] == 0:
        now = datetime.utcnow().isoformat()
        cur.execute(
            "INSERT INTO persona (id, prompt, updated_at) VALUES (1, ?, ?)",
            (DEFAULT_PROMPT, now)
        )
        cur.execute(
            "INSERT INTO persona_history (prompt, saved_at, note) VALUES (?, ?, ?)",
            (DEFAULT_PROMPT, now, "초기 기본 프롬프트")
        )

    conn.commit()
    conn.close()

# 서버 시작 시 DB 초기화
init_db()

# ─── 인증 의존성 ────────────────────────────────────────────────────────────────
def verify_admin(x_admin_key: Optional[str] = Header(None)):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=401, detail="관리자 키가 올바르지 않습니다.")
    return True

# ─── Pydantic 모델 ──────────────────────────────────────────────────────────────
class PersonaResponse(BaseModel):
    prompt: str
    updated_at: str
    updated_by: str

class PersonaUpdateRequest(BaseModel):
    prompt: str
    note: Optional[str] = None

class HistoryItem(BaseModel):
    id: int
    prompt: str
    saved_at: str
    saved_by: str
    note: Optional[str]

# ─── API 엔드포인트 ─────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def root():
    return {"service": "Klleon Persona API", "version": "1.0.0", "status": "running"}

@app.get("/api/persona", response_model=PersonaResponse, summary="현재 페르소나 조회")
def get_persona(db: sqlite3.Connection = Depends(get_db)):
    """
    Android 앱이 시작 시 호출하는 엔드포인트.
    현재 활성화된 페르소나 프롬프트를 반환합니다.
    인증 불필요 (앱에서 자유롭게 조회 가능).
    """
    row = db.execute("SELECT prompt, updated_at, updated_by FROM persona WHERE id = 1").fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="프롬프트가 설정되지 않았습니다.")
    return PersonaResponse(
        prompt=row["prompt"],
        updated_at=row["updated_at"],
        updated_by=row["updated_by"]
    )

@app.put("/api/persona", response_model=PersonaResponse, summary="페르소나 업데이트")
def update_persona(
    body: PersonaUpdateRequest,
    db: sqlite3.Connection = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """
    웹 관리 페이지에서 호출하는 엔드포인트.
    페르소나 프롬프트를 업데이트하고 이력을 저장합니다.
    헤더에 X-Admin-Key 필요.
    """
    if not body.prompt.strip():
        raise HTTPException(status_code=400, detail="프롬프트가 비어 있습니다.")

    now = datetime.utcnow().isoformat()

    # 현재 프롬프트 업데이트
    db.execute(
        "UPDATE persona SET prompt = ?, updated_at = ?, updated_by = 'admin' WHERE id = 1",
        (body.prompt.strip(), now)
    )

    # 이력 저장
    db.execute(
        "INSERT INTO persona_history (prompt, saved_at, saved_by, note) VALUES (?, ?, 'admin', ?)",
        (body.prompt.strip(), now, body.note or "웹에서 수정")
    )
    db.commit()

    return PersonaResponse(
        prompt=body.prompt.strip(),
        updated_at=now,
        updated_by="admin"
    )

@app.get("/api/persona/history", summary="변경 이력 조회")
def get_history(
    limit: int = 20,
    db: sqlite3.Connection = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """
    최근 변경 이력을 반환합니다 (최대 20건).
    헤더에 X-Admin-Key 필요.
    """
    rows = db.execute(
        "SELECT id, prompt, saved_at, saved_by, note FROM persona_history ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    return [dict(row) for row in rows]

@app.post("/api/persona/restore/{history_id}", summary="이전 프롬프트로 복원")
def restore_persona(
    history_id: int,
    db: sqlite3.Connection = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """
    특정 이력 ID의 프롬프트로 복원합니다.
    """
    row = db.execute(
        "SELECT prompt FROM persona_history WHERE id = ?", (history_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="해당 이력을 찾을 수 없습니다.")

    now = datetime.utcnow().isoformat()
    db.execute(
        "UPDATE persona SET prompt = ?, updated_at = ?, updated_by = 'admin' WHERE id = 1",
        (row["prompt"], now)
    )
    db.execute(
        "INSERT INTO persona_history (prompt, saved_at, saved_by, note) VALUES (?, ?, 'admin', ?)",
        (row["prompt"], now, f"이력 #{history_id}에서 복원")
    )
    db.commit()
    return {"message": f"이력 #{history_id}로 복원되었습니다.", "updated_at": now}

# ─── 정적 파일 서빙 (React 빌드 결과물) ────────────────────────────────────────
# React 빌드 후 dist/ 디렉토리가 생성되면 활성화
STATIC_DIR = os.path.join(os.path.dirname(__file__), "dist")
if os.path.exists(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

# ─── 서버 실행 (Railway 등 클라우드 배포용) ────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
