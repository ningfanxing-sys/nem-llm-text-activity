
'Check numerical source inventories and timestamp records.'
from __future__ import annotations
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
ROUTES = {'AP5': ('AP5', 'scoring_callback'), 'AP6': ('AP5', 'AP6', 'notice_delays', 'scoring_callback')}
FORBIDDEN = {'state', 'host_state', 'sealed', 'seal', 'seals', 'scored', 'scoring', 'score', 'scores', 'prediction', 'predictions', 'model', 'models', 'evaluation', 'run', 'private', '.git', '.aws', '.llm_client', '__pycache__', 'production_callback'}

class _Core:


    def __init__(self, values):
        self._values = values

    def __getattr__(self, name):
        if name in {'read', 'sha', 'identity', 'checked', 'write', 'contained', 'no_symlink_path'}:
            name = '_' + name
        try:
            return self._values[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

class _RuntimeAuthorities:

    def __init__(self, association, core):
        self.a, self.c = (association, core)
        self.grant_record = None

    def family(self, path):
        raw = os.fsdecode(os.fspath(path))
        p = Path(os.path.abspath(raw))
        rows = self.a._science_policy.get('families', {})
        exact = [name for name, row in rows.items() if p == self.a.q / row['freeze'] or p in {self.a.q / row['root'] / leaf for leaf in row['names']}]
        self.c.require(len(exact) <= 1, 'Ambiguous runtime family alias')
        if exact:
            return exact[0]
        return next((name for name, row in rows.items() if p.is_relative_to(self.a.q / row['root'])), None)

    def _token(self, path):
        raw = os.fsdecode(os.fspath(path))
        p = Path(raw)
        self.c.require(p.is_absolute() and '..' not in p.parts and (raw == str(p)), 'G39 noncanonical path/alias: ' + raw)
        return self.c.no_symlink_path(p)

    def canonical(self, path):
        p = self._token(path)
        raw = str(p)
        self.c.require(p.is_file() and stat.S_ISREG(p.lstat().st_mode), 'G39 requires an exact regular metadata/source file: ' + raw)
        self.c.require(self.a.metadata_root(p), 'G39 refuses payload/secret path: ' + raw)
        return p

    def relative(self, name):
        self.c.require(isinstance(name, str) and bool(name), 'G39 census name required')
        p = Path(name)
        self.c.require(not p.is_absolute() and '..' not in p.parts and ('.' not in p.parts) and (name == p.as_posix()) and (not FORBIDDEN.intersection((x.lower() for x in p.parts))), 'G39 unsafe relative census name: ' + name)
        return p

    def utc(self, value):
        try:
            self.c.require(isinstance(value, str), 'G39 UTC field missing')
            parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
            self.c.require(parsed.utcoffset() == dt.timedelta(0), 'G39 requires aware UTC')
            return parsed
        except (ValueError, TypeError) as exc:
            raise self.c.Refusal('G39 invalid UTC field') from exc

    def census(self, family):
        policy = self.a._science_policy['families'][family]
        root = self.a.q / self.relative(policy['root'])
        names = policy['names']
        self.c.require(isinstance(names, list) and names and (len(names) == len(set(names))), 'Empty/duplicate declared exact census')
        result = {}
        for name in names:
            self.c.require(not any((x in name for x in '*?[]')), 'Wildcard is not an exact runtime name')
            result[name] = self.canonical(root / self.relative(name))
        self.c.require(any((p.suffix == '.py' for p in result.values())), 'Runtime census has no code')
        return result

    def _snapshot_json(self, path, item):
        self.c.require(self.c.ACTIVE is self.a and self.a._validation_depth > 0, 'Private verified timestamp_checks decoder only')
        allowed = {self.a.out / 'T5_BINDING.json', *(self.a.q / row['freeze'] for row in self.a._science_policy['families'].values())}
        self.c.require(self.canonical(path) in allowed, 'Not an exact timestamp_checks metadata path')
        payload = Path(path).read_bytes()
        self.c.require(len(payload) == item['bytes'] and hashlib.sha256(payload).hexdigest() == item['sha256'], 'Metadata identity drift')

        def pairs(rows):
            result = {}
            for key, value in rows:
                self.c.require(key not in result, 'Duplicate JSON timestamp_checks key')
                result[key] = value
            return result
        return json.loads(payload, object_pairs_hook=pairs, parse_constant=lambda value: (_ for _ in ()).throw(self.c.Refusal('Nonfinite JSON')))

    def _t5(self):
        path = self.canonical(self.a.out / 'T5_BINDING.json')
        actual = self.c.identity(path)
        self.c.require(self.a._authority_files.get(str(path)) == actual, 'G39 requires independently verified C T5 binding identity')
        if self.grant_record:
            self.c.require(actual == self.grant_record['t5'], 'G39 T5 binding identity drift')
        value = self._snapshot_json(path, actual)
        self.c.require(value.get('state') == 'T5_VERIFIED' and value.get('source_verified') is True, 'G39 verified C T5 required')
        self.utc(value.get('utc'))
        rows = value.get('files')
        self.c.require(isinstance(rows, list), 'G39 uses C list-form T5 files only')
        indexed = {}
        for row in rows:
            self.c.require(isinstance(row, dict) and set(row) == {'path', 'bytes', 'sha256'} and (type(row['bytes']) is int) and (row['bytes'] >= 0) and isinstance(row['sha256'], str) and re.fullmatch('[0-9a-f]{64}', row['sha256']), 'G39 exact full T5 identity required')
            p = self.canonical(row['path'])
            self.c.require(p.is_relative_to(self.a.project), 'G39 foreign T5 path')
            self.c.require(str(p) not in indexed, 'G39 duplicate T5 member')
            indexed[str(p)] = row
        return (actual, value, indexed)

    def _candidate(self, families):
        t5, value, indexed = self._t5()
        identities = {}
        declarations = {}
        for family in families:
            policy = self.a._science_policy['families'][family]
            self.c.require(set(policy) == {'root', 'freeze', 'schema', 'state', 'inventory_field', 'inventory_format', 'inventory_base', 'declared_census_field', 'names'}, 'Exact reviewed owner policy required')
            root = self.a.q / self.relative(policy['root'])
            freeze = self.canonical(self.a.q / self.relative(policy['freeze']))
            self.c.require(freeze.is_relative_to(root), 'Freeze outside family root')
            fi = self.c.identity(freeze)
            self.c.require(indexed.get(str(freeze)) == fi, 'Freeze missing/drifted/not T5-listed')
            f = self._snapshot_json(freeze, fi)
            self.c.require(f.get('schema') == policy['schema'] and f.get('state') == policy['state'], 'Wrong/unfrozen successor')
            self.c.require(self.utc(f.get('frozen_utc')) < self.utc(value['utc']), 'Successor freeze after/equal T5')
            census = self.census(family)
            declared = f.get(policy['declared_census_field'])
            self.c.require(isinstance(declared, list) and len(declared) == len(set(declared)) and (set(declared) == set(census)), 'Declared census missing/extra/duplicate')
            inventory = f.get(policy['inventory_field'])
            pins = {}
            if policy['inventory_format'] == 'relative_sha_dict':
                self.c.require(isinstance(inventory, dict), 'Exact relative SHA dictionary required')
                base = self.a.q / self.relative(policy['inventory_base'])
                for name, digest in inventory.items():
                    p = self.canonical(base / self.relative(name))
                    self.c.require(p.is_relative_to(root), 'Family inventory escaped root')
                    key = str(p.relative_to(root))
                    self.c.require(key not in pins, 'Duplicate family member')
                    pins[key] = {'sha256': digest}
            else:
                self.c.require(policy['inventory_format'] in {'absolute_sha_list', 'absolute_bytes_sha_list'} and isinstance(inventory, list), 'Exact declared inventory format required')
                fields = {'path', 'sha256'} if policy['inventory_format'] == 'absolute_sha_list' else {'path', 'bytes', 'sha256'}
                for row in inventory:
                    self.c.require(isinstance(row, dict) and set(row) == fields, 'Wrong inventory identity fields')
                    p = self.canonical(row['path'])
                    self.c.require(p.is_relative_to(root), 'Family inventory escaped root')
                    key = str(p.relative_to(root))
                    self.relative(key)
                    self.c.require(key not in pins, 'Duplicate family member')
                    pins[key] = {k: v for k, v in row.items() if k != 'path'}
            self.c.require(set(pins) == set(census), 'Omitted/extra runtime inventory')
            for key, p in census.items():
                actual = self.c.identity(p)
                pin = pins[key]
                self.c.require(actual['sha256'] == pin['sha256'] and ('bytes' not in pin or (type(pin['bytes']) is int and actual['bytes'] == pin['bytes'])), 'Runtime source identity drift')
                self.c.require(indexed.get(str(p)) == actual, 'Runtime member not exact T5-listed')
                self.c.require(str(p) not in identities, 'Overlapping family identity')
                identities[str(p)] = actual
            self.c.require(str(freeze) not in identities, 'Freeze/member alias')
            identities[str(freeze)] = fi
            declarations[family] = tuple(sorted(census))
        for path, item in identities.items():
            self.c.require(self.c.identity(self.canonical(path)) == item, 'Runtime changed during verification')
        self.c.require(self.c.identity(self.a.out / 'T5_BINDING.json') == t5, 'T5 changed during verification')
        return dict(families=tuple(families), t5=t5, files=identities, census=declarations)

    def grant(self, route):
        self.c.require(self.c.ACTIVE is self.a and (not self.a._preparing) and (not self.a._metadata_only), 'G39 runtime route requires installed postscore association')
        try:
            self.c.require(route in ROUTES, 'G39 unknown AP route')
            self.a.verify_t5_coverage()
            with self.a._validation():
                candidate = self._candidate(ROUTES[route])
            self.revoke()
            self.grant_record = candidate
            return dict(route=route, families=list(candidate['families']), t5=dict(candidate['t5']), members=len(candidate['files']))
        except BaseException:
            self.revoke()
            raise

    def revalidate(self):
        if self.grant_record is None:
            return
        previous = self.grant_record
        try:
            with self.a._validation():
                current = self._candidate(previous['families'])
            self.c.require(current == previous, 'G39 granted family identity/census drift')
        except BaseException:
            self.revoke()
            raise

    def member(self, path):
        try:
            self.c.require(self.c.ACTIVE is self.a, 'G39 inactive family route')
            p = self.canonical(path)
            self.c.require(self.family(p) is not None, 'G39 path is not a reviewed family')
            self.c.require(self.grant_record is not None, 'G39 family has no runtime authorization')
            self.revalidate()
            self.c.require(str(p) in self.grant_record['files'], 'G39 file outside frozen census')
            return self.grant_record['files'][str(p)]
        except BaseException:
            self.revoke()
            raise

    def source_bytes(self, path):
        try:
            item = self.member(path)
            self.c.require(Path(path).suffix == '.py', 'G39 loader accepts source Python only')
            with self.a._validation():
                payload = Path(path).read_bytes()
            self.c.require(len(payload) == item['bytes'] and hashlib.sha256(payload).hexdigest() == item['sha256'], 'G39 compile snapshot identity drift')
            return payload
        except BaseException:
            self.revoke()
            raise

    def revoke(self):
        self.grant_record = None
        for name, module in list(sys.modules.items()):
            path = getattr(module, '__file__', None)
            if path and self.family(path) is not None:
                sys.modules.pop(name, None)

    def guard_module(self, module):

        import types
        import functools
        timestamp_checks = self
        source = module.__file__

        class FamilyModule(types.ModuleType):

            def __getattribute__(self, name):
                value = types.ModuleType.__getattribute__(self, name)
                if not name.startswith('_') and isinstance(value, types.FunctionType) and (value.__module__ == types.ModuleType.__getattribute__(self, '__name__')):

                    @functools.wraps(value)
                    def guarded(*args, **kwargs):
                        timestamp_checks.member(source)
                        result = value(*args, **kwargs)
                        timestamp_checks.member(source)
                        if hasattr(result, '__enter__') and hasattr(result, '__exit__'):
                            return FamilyContext(result, timestamp_checks, source)
                        return result
                    return guarded
                return value
        module.__class__ = FamilyModule
        module.__dict__['_g39_runtime_authority'] = self

    def cached_module(self, module):
        path = getattr(module, '__file__', None)
        if path and self.family(path) is not None:
            try:
                self.member(path)
                self.c.require(vars(module).get('_g39_runtime_authority') is self, 'G39 cached module was not loaded through the verified loader')
            except BaseException:
                self.revoke()
                raise
        return module

class FamilyContext:


    def __init__(self, context, timestamp_checks, source):
        self.context, self.timestamp_checks, self.source = (context, timestamp_checks, source)

    def __enter__(self):
        self.timestamp_checks.member(self.source)
        result = self.context.__enter__()
        try:
            self.timestamp_checks.member(self.source)
        except BaseException:
            self.context.__exit__(*sys.exc_info())
            raise
        return result

    def __exit__(self, *args):
        try:
            self.timestamp_checks.member(self.source)
        except BaseException:
            self.context.__exit__(*sys.exc_info())
            raise
        result = self.context.__exit__(*args)
        self.timestamp_checks.member(self.source)
        return result
