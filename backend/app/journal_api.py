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
    with connection() as conn:
        row=conn.execute("""INSERT INTO trade_journal
            (user_id,symbol,side,setup,timeframe,entry,stop_loss,take_profit,outcome,pnl,r_multiple,notes,tags,closed_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s) RETURNING id,created_at""",
            (user["id"],entry.symbol.upper(),entry.side,entry.setup,entry.timeframe,entry.entry,entry.stop_loss,entry.take_profit,
             entry.outcome,entry.pnl,entry.r_multiple,entry.notes,json.dumps(entry.tags),None)).fetchone()
    return {"id":int(row[0]),"created_at":row[1]}

@router.delete("/{entry_id}")
def delete_journal(entry_id:int,user=Depends(current_user)):
    with connection() as conn:
        row=conn.execute("DELETE FROM trade_journal WHERE id=%s AND user_id=%s RETURNING id",(entry_id,user["id"])).fetchone()
    if not row: raise HTTPException(404,"Journal entry not found")
    return {"deleted":True,"id":int(row[0])}

@router.get("/stats")
def journal_stats(user=Depends(current_user)):
    with connection() as conn:
        row=conn.execute("""SELECT COUNT(*),
                   COUNT(*) FILTER (WHERE UPPER(COALESCE(outcome,'')) IN ('WIN','WON','TP')),
                   COUNT(*) FILTER (WHERE UPPER(COALESCE(outcome,'')) IN ('LOSS','LOST','SL')),
                   COALESCE(SUM(pnl),0),COALESCE(SUM(r_multiple),0)
                   FROM trade_journal WHERE user_id=%s""",(user["id"],)).fetchone()
    entries=int(row[0] or 0); wins=int(row[1] or 0); losses=int(row[2] or 0)
    return {"entries":entries,"wins":wins,"losses":losses,"win_rate":round(wins/entries*100,2) if entries else 0,"total_pnl":round(float(row[3] or 0),2),"total_r":round(float(row[4] or 0),4)}


def record_closed_trade(position, r_multiple=None):
    with connection() as conn:
        conn.execute("""INSERT INTO trade_journal
            (user_id,symbol,side,setup,timeframe,entry,stop_loss,take_profit,outcome,pnl,r_multiple,notes,closed_at)
            VALUES (%s,%s,%s,'executed trade','MTF',%s,%s,%s,%s,%s,%s,%s,now())""",
            (position.user_id,position.symbol,position.side,position.entry,position.stop_loss,position.take_profit,
             "WIN" if float(position.realized_pnl or 0)>0 else "LOSS" if float(position.realized_pnl or 0)<0 else "BREAKEVEN",
             position.realized_pnl,r_multiple or 0.0,f"Closed automatically or manually: {position.close_reason or 'unknown'}"))
