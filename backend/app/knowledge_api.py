from fastapi import APIRouter, HTTPException
from .knowledge import all_knowledge, INDICATORS, CANDLES, SIGNALS, MACRO_TOPICS

router=APIRouter(prefix="/v1/knowledge",tags=["knowledge"])

@router.get("")
def knowledge_index():
    data=all_knowledge()
    return {
        "mission":data["mission"],
        "principles":data["principles"],
        "counts":{"indicators":len(INDICATORS),"candles":len(CANDLES),"signals":len(SIGNALS),"macro_topics":len(MACRO_TOPICS)},
        "sources":data["sources"],
    }

@router.get("/library")
def knowledge_library():
    return all_knowledge()

@router.get("/{kind}/{slug}")
def knowledge_item(kind:str,slug:str):
    mapping={"indicators":INDICATORS,"candles":CANDLES,"signals":SIGNALS,"macro":MACRO_TOPICS}
    items=mapping.get(kind)
    if items is None: raise HTTPException(404,"Knowledge category not found")
    item=next((x for x in items if x.get("slug")==slug),None)
    if item is None: raise HTTPException(404,"Knowledge item not found")
    return item
