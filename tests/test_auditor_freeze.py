"""STEP 13.5: Auditor on a mint with freeze authority set -> red at layer 2, layers 3-8 'not checked'."""
import asyncio
from agents.auditor import Auditor


def test_freeze_red(desk):
    m = "FreezeMint111111111111111111111111111pump"
    desk.db.exec("INSERT INTO coins(mint,name,symbol,migrated_at) VALUES(?,?,?,?)", (m, "Frz", "FRZ", 0))

    async def acct(mint):   # shape of logs/raw/rpc_getAccountInfo.json, freeze set
        return {"result": {"value": {"owner": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                "data": {"parsed": {"info": {"mintAuthority": None, "freezeAuthority": "FrzAuth1111111111111111111111111111", "supply": "1000000000", "decimals": 6}}}}}}
    desk.rpc.account_info = acct
    out = asyncio.run(Auditor(desk).audit({"mint": m}, forward=True))
    L = out["layers"]
    assert L[0]["pass"] is True and L[0]["value"] == "Revoked"
    assert L[1]["pass"] is False and L[1]["value"] == "freeze not revoked"
    assert all(l["value"] == "not checked" and l["pass"] is None for l in L[2:]) and len(L) == 8
    act = desk.db.one("SELECT * FROM activity ORDER BY id DESC LIMIT 1")
    assert act["subtitle"] == "Auditor · freeze not revoked" and act["value"] == "Skipped"
    for l in L:
        print(l["n"], l["name"], l["pass"], l["value"])
