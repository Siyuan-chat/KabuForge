"""Validate semantic identity, mirrored sections, examples and local links."""
from pathlib import Path
import json
import re


def check(root):
    manifest = json.loads((root/'docs_manifest.yaml').read_text(encoding='utf-8'))
    errors = []; seen = set()
    for doc in manifest['documents']:
        if doc['id'] in seen: errors.append('duplicate doc id: '+doc['id'])
        seen.add(doc['id']); snippets = []
        if set(doc['locales'])!={'en_US','zh_CN','ja_JP'}: errors.append('missing locale: '+doc['id'])
        for locale,path in doc['locales'].items():
            file = root/path
            if not file.exists(): errors.append('missing '+path); continue
            text = file.read_text(encoding='utf-8')
            for key,value in {'doc_id':doc['id'],'version':doc['version'],'locale':locale}.items():
                if not re.search(r'^'+key+r':\s*'+re.escape(str(value))+r'\s*$',text,re.M): errors.append('identity mismatch: '+path+' '+key)
            for section in doc['sections']:
                if '<!-- section:'+section+' -->' not in text and '<!-- section: '+section+' -->' not in text: errors.append('missing section: '+path+' '+section)
            snippets.append(re.findall(r'```[^\n]*\n(.*?)```',text,re.S))
            for target in re.findall(r'\]\(([^)]+)\)',text):
                if '://' in target or target.startswith('#'): continue
                link = target.split('#')[0]
                if link and not (file.parent/link).exists(): errors.append('broken link: '+path+' '+target)
        if snippets and any(item!=snippets[0] for item in snippets): errors.append('snippet drift: '+doc['id'])
    return errors


if __name__=='__main__':
    root = Path(__file__).resolve().parents[1]
    errors = check(root)
    print(json.dumps({'documents_checked':len(json.loads((root/'docs_manifest.yaml').read_text())['documents']),'errors':errors}))
    raise SystemExit(bool(errors))
