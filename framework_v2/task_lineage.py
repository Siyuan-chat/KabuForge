"""Additive task correlation receipts; never part of financial result identity."""
import json
from pathlib import Path


def write_lineage(directory, *, task_id, operation, request_ref, input_sha256,
                  execution_host, job_id=None, run_id=None,
                  input_identity_kind='request_bytes', request_ref_base='task_directory',
                  filename='task_lineage.json'):
    if Path(filename).name != filename:
        raise ValueError('lineage filename must stay in its artifact directory')
    value = {'schema':'kabuforge.task_lineage.v1','task_id':task_id,
             'job_id':job_id,'run_id':run_id,'operation':operation,
             'input_sha256':input_sha256,'input_identity_kind':input_identity_kind,
             'request_ref':request_ref,'request_ref_base':request_ref_base,
             'execution_host':execution_host}
    with (Path(directory)/filename).open('x',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,allow_nan=False,indent=2)
    return value
