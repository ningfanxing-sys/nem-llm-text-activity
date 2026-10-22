'Check the saved forecast timestamp identities.'
from contextlib import contextmanager
import io
import json
from pathlib import Path
import sys
from forecast_check_helpers import checked as live_checked, document as live_document, row as live_row, require

HERE = Path(__file__).absolute().parent
INDEX = dict(path=str(HERE/'a12/history/INDEX.json'), bytes=110729,
             sha256='99f0ec6a0e29e3086e2055d0561c2bed00ccaf40f1de0a5573c8acb189f988d6')


class HistoricalT4G:
    def __init__(self, native, *, index=INDEX, current=None):
        self.native = native
        self.index = index
        self.history = live_document(index)
        self.rows = {r['original']['path']: r for r in self.history['files']}
        require(len(self.rows) == len(self.history['files']), 'A12 duplicate historical logical path')
        if current is None:
            build = live_document(live_row(HERE/'BUILD_IDENTITY.json'))
            current = [dict(path=str(HERE/name), **pin) for name,pin in build['files'].items()]
            current += [live_row(HERE/'BUILD_IDENTITY.json')]
        self.current = {r['path']: r for r in current}
        require(len(self.current) == len(current), 'A12 duplicate current identity')

        native.sources.recheck()
        for item in current:
            live_checked(item)
        self.current_mode = False

    def historical(self, item):
        entry = self.rows.get(item['path'])
        require(entry is not None and entry['original'] == item,
                'A12 exact historical identity missing: '+item['path'])
        archive = entry['archive']
        require(all(archive[k] == item[k] for k in ('bytes','sha256')), 'A12 archive identity mismatch')
        return live_checked(archive)

    def checked(self, item, sources=None):
        if not self.current_mode and item['path'] in self.rows and self.rows[item['path']]['original'] == item:

            return self.historical(item)
        return live_checked(item, sources)

    def document(self, item, sources=None):
        return json.loads(self.checked(item, sources))

    def row(self, path, data=None):
        key = str(Path(path).absolute())
        if data is None and not self.current_mode and key in self.rows:
            item = self.rows[key]['original']
            self.historical(item)
            return dict(item)
        return live_row(path, data)

    @contextmanager
    def installed(self):

        saved = []
        modules = ('forecast_check_helpers','forecast_checks_cli','forecast_runtime_metadata','forecast_timestamps',
                   'forecast_readers','forecast_source_contracts','forecast_context','forecast_contract_history','forecast_time_alignment')
        try:
            for name in modules:
                module = __import__(name)
                for attr, original, replacement in (
                    ('checked',live_checked,self.checked), ('document',live_document,self.document),
                    ('row',live_row,self.row)):
                    if getattr(module, attr, None) is original:
                        saved.append((module,attr,original));setattr(module,attr,replacement)
            previous_open = Path.open
            def verification_open(path, mode='r', buffering=-1, encoding=None, errors=None, newline=None):
                key = str(path.absolute())
                if (not self.current_mode and key in self.rows and path.suffix == '.json'
                        and mode in ('r','rt','rb')):
                    data = self.historical(self.rows[key]['original'])
                    return io.BytesIO(data) if 'b' in mode else io.StringIO(data.decode(encoding or 'utf-8', errors or 'strict'))
                return previous_open(path,mode,buffering,encoding,errors,newline)
            Path.open = verification_open
            saved.append((Path,'open',previous_open))
            old_recheck = self.native.sources.recheck
            def current_recheck():
                old_mode=self.current_mode;self.current_mode=True
                try:return old_recheck()
                finally:self.current_mode=old_mode
            self.native.sources.recheck = current_recheck
            saved.append((self.native.sources,'recheck',old_recheck))
            old_crypto = self.native.crypto
            @contextmanager
            def crypto(required):
                with old_crypto(required) as timestamp_checks:
                    previous=timestamp_checks.read_metadata
                    def read_metadata(path):
                        key=str(Path(path).absolute())
                        if key in self.rows:return self.historical(self.rows[key]['original'])
                        return previous(path)
                    timestamp_checks.read_metadata=read_metadata
                    try:yield timestamp_checks
                    finally:timestamp_checks.read_metadata=previous
            self.native.crypto=crypto
            saved.append((self.native,'crypto',old_crypto))
            yield self
            self.native.sources.recheck()
            for item in self.current.values():
                self.current_mode=True
                try:live_checked(item)
                finally:self.current_mode=False
        finally:
            for module,attr,original in reversed(saved):setattr(module,attr,original)

