import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from .auth import current_user
from .db import connection

router=APIRouter(prefix="/v1/journal",tags=["journal"])

class JournalEntry(BaseModel):
    symbol:str=Field(min_length=2,max_length=30)
    side:str|None=None
    setup:str|None=None
    timeframe:str|None=None
    entry:float|None=None
    stop_loss:float|None=None
    take_profit:float|None=None
    outcome:str|None=None
    pnl:float|None=None
    r_multiple:float|None=None
    notes:str=""
    tags:list[str]=[]

def ensure_journal_tables():
    with connection() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS trade_journal(
            id BIGSERIAL PRIMARY KEY,user_id TEXT NOT NULL,symbol TEXT NOT NULL,side TEXT,
            setup TEXT,timeframe TEXT,entry NUMERIC,stop_loss NUMERIC,take_profit NUMERIC,
            outcome TEXT,pnl NUMERIC,r_multiple NUMERIC,notes TEXT NOT NULL DEFAULT '',
            tags JSONB NOT NULL DEFAULT '[]'::jsonb,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            closed_at TIMESTAMPTZ)""")
        conn.execute("CREATE INDEX IF NOT EXISTS trade_journal_user_created_idx ON trade_journal(user_id,created_at DESC)")

@router.get("")
def list_journal(limit:int=50,user=Depends(current_user)):
    ensure_journal_tables()
    limit=max(1,min(int(limit),200))
    with connection() as conn:
        rows=conn.execute("""SELECT id,symbol,side,setup,timeframe,entry,stop_loss,take_profit,outcome,pnl,r_multiple,notes,tags,created_at,closed_at
            FROM trade_journal WHERE user_id=%s ORDER BY created_at DESC LIMIT %s""",(user["id"],limit)).fetchall()
    return {"entries":[
        {"id":r[0],"symbol":r[1],"side":r[2],"setup":r[3],"timeframe":r[4],"entry":r[5],"stop_loss":r[6],"take_profit":r[7],
         "outcome":r[8],"pnl":r[9],"r_multiple":r[10],"notes":r[11],"tags":r[12] or [],"created_at":r[13],"closed_at":r[14]}
        for r in rows
    ]}

@router.post("")
def create_journal(entry:JournalEntry,user=Depends(current_user)):
    ensure_journal_tables()
    with connection() as conn:
        row=conn.execute("""INSERT INTO trade_journal
            (user_id,symbol,side,setup,timeframe,entry,stop_loss,take_profit,outcome,pnl,r_multiple,notes,tags,closed_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s) RETURNING id,created_at""",
            (user["id"],entry.symbol.upper(),entry.side,entry.setup,entry.timeframe,entry.entry,entry.stop_loss,entry.take_profit,
             entry.outcome,entry.pnl,entry.r_multiple,entry.notes,json.dumps(entry.tags),None)).fetchone()
    return {"id":int(row[0]),"created_at":row[1]}

@router.delete("/{entry_id}")
def delete_journal(entry_id:int,user=Depends(current_user)):
    ensure_journal_tables()
    with connection() as conn:
        row=conn.execute("DELETE FROM trade_journal WHERE id=%s AND user_id=%s RETURNING id",(entry_id,user["id"])).fetchone()
    if not row: raise HTTPException(404,"Journal entry not found")
    return {"deleted":True,"id":int(row[0])}

@router.get("/stats")
def journal_stats(user=Depends(current_user)):
    ensure_journal_tables()
    with connection() as conn:
        rows=conn.execute("SELECT outcome,pnl,r_multiple FROM trade_journal WHERE user_id=%s",(user["id"],)).fetchall()
    pnl=sum(float(r[1] or 0) for r in rows)
    rvals=[float(r[2]) for r in rows if r[2] is not None]
    wins=sum(1 for r in rows if str(r[0]).upper() in ("WIN","WON","TP"))
    losses=sum(1 for r in rows if str(r[0]).upper() in ("LOSS","LOST","SL"))
    return {"entries":len(rows),"wins":wins,"losses":losses,"win_rate":round(wins/len(rows)*100,2) if rows else 0,"total_pnl":round(pnl,2),"total_r":round(sum(rvals),4)}
