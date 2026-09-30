"""Explicit, rebuildable SQLite factor cache with a non-executable JSON codec."""
import hashlib
import json
from pathlib import Path
import sqlite3
from datetime import datetime, date
from decimal import Decimal
import math
from contextlib import closing
from collections.abc import Mapping
import pandas as pd
from .factors import FactorResult, FactorContractError

def encode(value):
    if value is pd.NA: return ["NA"]
    if value is pd.NaT: return ["NaT"]
    if value is None or isinstance(value,(str,bool,int)): return ["literal",value]
    if isinstance(value,float):
        return ["float",repr(value)]
    if isinstance(value,Decimal): return ["decimal",str(value)]
    if isinstance(value,(datetime,pd.Timestamp)): return ["timestamp",value.isoformat()]
    if isinstance(value,date): return ["date",value.isoformat()]
    if isinstance(value,pd.DataFrame):
        if isinstance(value.index,pd.MultiIndex): raise FactorContractError("cache MultiIndex unsupported")
        return ["frame",list(value.columns),[str(d) for d in value.dtypes],
            [[encode(v) for v in row] for row in value.itertuples(index=False,name=None)],
            [encode(v) for v in value.index],str(value.index.dtype),value.index.name]
    if isinstance(value,Mapping): return ["map",[[encode(k),encode(v)] for k,v in value.items()]]
    if isinstance(value,tuple): return ["tuple",[encode(v) for v in value]]
    if isinstance(value,list): return ["list",[encode(v) for v in value]]
    if hasattr(value,"item"): return encode(value.item())
    raise FactorContractError("unsupported factor cache value: "+type(value).__name__)

def decode(item):
    tag=item[0]
    if tag=="literal": return item[1]
    if tag=="NA": return pd.NA
    if tag=="NaT": return pd.NaT
    if tag=="float": return float(item[1])
    if tag=="decimal": return Decimal(item[1])
    if tag=="timestamp": return pd.Timestamp(item[1])
    if tag=="date": return date.fromisoformat(item[1])
    if tag=="map": return {decode(k):decode(v) for k,v in item[1]}
    if tag=="list": return [decode(v) for v in item[1]]
    if tag=="tuple": return tuple(decode(v) for v in item[1])
    if tag=="frame":
        frame=pd.DataFrame([[decode(v) for v in row] for row in item[3]],columns=item[1])
        for column,dtype in zip(item[1],item[2]): frame[column]=frame[column].astype(dtype)
        frame.index=pd.Index([decode(v) for v in item[4]],dtype=item[5],name=item[6])
        return frame
    raise FactorContractError("unknown factor cache codec tag")

class FactorCache:
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS factor_cache_v1(cache_key TEXT PRIMARY KEY,payload TEXT NOT NULL,sha256 TEXT NOT NULL)")

    @staticmethod
    def _key(key):
        if not isinstance(key,str) or len(key)!=64 or any(c not in "0123456789abcdef" for c in key):
            raise FactorContractError("invalid factor cache key")

    def get(self,key):
        self._key(key)
        with closing(sqlite3.connect(self.path)) as db, db:
            row=db.execute("SELECT payload,sha256 FROM factor_cache_v1 WHERE cache_key=?",(key,)).fetchone()
        if row is None: return None
        if hashlib.sha256(row[0].encode()).hexdigest()!=row[1]: raise FactorContractError("corrupt factor cache checksum")
        value=decode(json.loads(row[0]))
        return FactorResult.from_legacy_dict(value["result"],binding_id=value["binding_id"])

    def put(self,key,result):
        self._key(key)
        payload=json.dumps(encode({"binding_id":result.binding_id,"result":result.to_legacy_dict()}),ensure_ascii=False,separators=(",",":"),allow_nan=False)
        digest=hashlib.sha256(payload.encode()).hexdigest()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            previous=db.execute("SELECT payload FROM factor_cache_v1 WHERE cache_key=?",(key,)).fetchone()
            if previous is not None:
                if previous[0]!=payload: raise FactorContractError("different result for immutable factor cache key")
            else: db.execute("INSERT INTO factor_cache_v1 VALUES(?,?,?)",(key,payload,digest))
