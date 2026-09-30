"""Explicit narrow legacy-factor conversion; original bytes remain reviewable."""
from pathlib import Path
import hashlib
from .config import _read_json_snapshot
from .factors import FactorSpec
from .legacy_provider import BuiltinFactors, REQUIRED_DATASETS
from .local_io import write_new

def convert_factor(source, destination, *, name, factor_id, lookback):
    """Convert only a plain legacy factor parameter object.

    Composite strategy/regime/allocation conversion is deliberately rejected by
    this API's shape; those semantics require a separate compatibility adapter.
    A full old engine config must never be treated as factor parameters.
    """
    source=Path(source); destination=Path(destination)
    # Parse and retain the exact same byte snapshot, including original formatting.
    raw=source.read_bytes()
    import json
    from .config import _unique_pairs,_reject_constant,_check_secrets,ConfigError
    parameters=json.loads(raw.decode("utf-8"),object_pairs_hook=_unique_pairs,parse_constant=_reject_constant)
    if not isinstance(parameters,dict): raise ConfigError("legacy factor parameters must be an object")
    _check_secrets(parameters,source)
    if type(lookback) is not int or lookback<0: raise ConfigError("explicit nonnegative lookback required")
    builtin=BuiltinFactors(); implementation=("public.momentum_12_1" if name == "residual_momentum" else "public."+name)
    if implementation not in builtin.versions: raise ConfigError("unknown legacy factor")
    config={"schema_version":"1.0","kind":"factor","id":factor_id,"version":"1",
        "implementation":{"id":implementation,"version":builtin.versions[implementation],"parameters":parameters},
        "data_requirements":[{"dataset":d,"fields":["index_code" if d=="index_prices" else "code","available_at"]} for d in REQUIRED_DATASETS[name]],
        "lookback":lookback,"output":{"name":name,"description":"Explicit conversion of local legacy parameters"},
        "metadata":{"original_sha256":hashlib.sha256(raw).hexdigest(),"original_file":"legacy_original.json",
                    "conversion":"public-factor-parameters-v1"}}
    from jsonschema import Draft202012Validator
    from .config import SCHEMA_DIR
    Draft202012Validator(json.loads((SCHEMA_DIR/"factor.schema.json").read_text())).validate(config)
    builtin.validate_spec(FactorSpec.from_config(config))
    destination.mkdir(parents=True,exist_ok=False)
    (destination/"legacy_original.json").write_bytes(raw)
    write_new(destination/"factor.json",config)
    return destination/"factor.json"
