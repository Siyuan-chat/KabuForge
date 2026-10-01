"""Validate formal docs, homepage links/anchors, package mirrors and licensing."""
from pathlib import Path
import json
import re
import tomllib
import hashlib
from urllib.parse import unquote, urlsplit

LOCALES = ('en_US', 'zh_CN', 'ja_JP')
HOMEPAGES = ('README.md', 'README.zh_CN.md', 'README.ja_JP.md')


def anchors(text):
    result = set(re.findall(r'\b(?:id|name)=["\']([^"\']+)["\']', text))
    counts = {}
    text = re.sub(r'```.*?```', '', text, flags=re.S)
    for heading in re.findall(r'^#{1,6}\s+(.+?)\s*#*\s*$', text, re.M):
        heading = re.sub(r'<[^>]+>', '', heading)
        heading = re.sub(r'\[([^]]+)\]\([^)]+\)', r'\1', heading)
        slug = re.sub(r'[^\w\- ]', '', heading.lower()).replace(' ', '-')
        count = counts.get(slug, 0)
        counts[slug] = count+1
        result.add(slug+(f'-{count}' if count else ''))
    return result


def local_links(root, file):
    text = re.sub(r'```.*?```', '', file.read_text(encoding='utf-8'), flags=re.S)
    targets = re.findall(r'\]\(([^)\s]+)(?:\s+[^)]*)?\)', text)
    targets += re.findall(r'\b(?:href|src|srcset)=["\']([^"\']+)["\']', text)
    errors = []
    for target in targets:
        parts = urlsplit(target.strip('<>'))
        if parts.scheme or parts.netloc: continue
        dest = (file.parent/unquote(parts.path)).resolve() if parts.path else file.resolve()
        label = file.relative_to(root).as_posix()+' '+target
        if not dest.is_relative_to(root.resolve()): errors.append('outside repository link: '+label)
        elif not dest.exists(): errors.append('broken link: '+label)
        elif parts.fragment and dest.suffix == '.md':
            if unquote(parts.fragment) not in anchors(dest.read_text(encoding='utf-8')):
                errors.append('missing anchor: '+label)
    return errors


def check_homepages(root):
    errors = []
    for path in HOMEPAGES:
        file = root/path
        if not file.exists(): errors.append('missing homepage: '+path); continue
        text = file.read_text(encoding='utf-8')
        for language_path in HOMEPAGES:
            if f']({language_path})' not in text:
                errors.append('language entry mismatch: '+path+' '+language_path)
        for token in ('AGPL-3.0-only','CITATION.cff','LICENSE_SCOPE.md','available_at','UNKNOWN','0.1.0rc1'):
            if token not in text: errors.append('homepage identity mismatch: '+path+' '+token)
        if 'license-MIT-' in text: errors.append('current license badge mismatch: '+path)
    return errors


def check_license(root):
    errors = []
    project = tomllib.loads((root/'pyproject.toml').read_text(encoding='utf-8'))['project']
    if project.get('license') != 'AGPL-3.0-only': errors.append('license metadata mismatch: pyproject.toml')
    if not {'LICENSE','NOTICE'} <= set(project.get('license-files',[])): errors.append('license file packaging mismatch')
    cff = (root/'CITATION.cff').read_text(encoding='utf-8')
    if not re.search(r'^license:\s*AGPL-3.0-only\s*$',cff,re.M): errors.append('license metadata mismatch: CITATION.cff')
    license_text = (root/'LICENSE').read_text(encoding='utf-8')
    if 'GNU AFFERO GENERAL PUBLIC LICENSE' not in license_text or 'Version 3, 19 November 2007' not in license_text:
        errors.append('AGPL license text mismatch')
    if hashlib.sha256(license_text.encode('utf-8')).hexdigest() != '0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0':
        errors.append('official AGPL text digest mismatch')
    notice = root/'NOTICE'
    if not notice.exists() or 'Permission is hereby granted' not in notice.read_text(encoding='utf-8'):
        errors.append('retained MIT notice missing')
    for locale in LOCALES:
        for name in ('DEVELOPMENT.md','CONTRIBUTING.md'):
            path = f'docs/{locale}/{name}'
            if 'AGPL-3.0-only' not in (root/path).read_text(encoding='utf-8'):
                errors.append('current license documentation mismatch: '+path)
    return errors


def check(root):
    manifest = json.loads((root/'docs_manifest.yaml').read_text(encoding='utf-8'))
    errors = []; seen = set(); files = set()
    for doc in manifest['documents']:
        if doc['id'] in seen: errors.append('duplicate doc id: '+doc['id'])
        seen.add(doc['id']); snippets = []
        if set(doc['locales'])!={'en_US','zh_CN','ja_JP'}: errors.append('missing locale: '+doc['id'])
        for locale,path in doc['locales'].items():
            file = root/path
            if not file.exists(): errors.append('missing '+path); continue
            files.add(file)
            text = file.read_text(encoding='utf-8')
            for key,value in {'doc_id':doc['id'],'version':doc['version'],'locale':locale}.items():
                if not re.search(r'^'+key+r':\s*'+re.escape(str(value))+r'\s*$',text,re.M): errors.append('identity mismatch: '+path+' '+key)
            for section in doc['sections']:
                if '<!-- section:'+section+' -->' not in text and '<!-- section: '+section+' -->' not in text: errors.append('missing section: '+path+' '+section)
            snippets.append(re.findall(r'```[^\n]*\n(.*?)```',text,re.S))
        if snippets and any(item!=snippets[0] for item in snippets): errors.append('snippet drift: '+doc['id'])
    for locale in LOCALES:
        for source in (root/'docs'/locale).rglob('*.md'):
            files.add(source)
            mirror = root/'framework_v2/docs'/locale/source.relative_to(root/'docs'/locale)
            if not mirror.exists() or source.read_bytes()!=mirror.read_bytes():
                errors.append('package mirror drift: '+source.relative_to(root).as_posix())
    for path in (*HOMEPAGES,'README.en.md','README.ja.md','LICENSE_SCOPE.md'):
        if (root/path).exists(): files.add(root/path)
    for file in sorted(files): errors.extend(local_links(root,file))
    errors.extend(check_homepages(root))
    errors.extend(check_license(root))
    return errors


if __name__=='__main__':
    root = Path(__file__).resolve().parents[1]
    errors = check(root)
    print(json.dumps({'documents_checked':len(json.loads((root/'docs_manifest.yaml').read_text())['documents']),'homepages_checked':len(HOMEPAGES),'errors':errors},ensure_ascii=False))
    raise SystemExit(bool(errors))
