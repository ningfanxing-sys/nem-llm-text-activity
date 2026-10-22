
'Recover gzip files and ordered split parts, checking the saved hashes.'
from __future__ import annotations
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile

BLOCK=1 << 20

def contained(root, relative):
    path=(root/relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Recovery path leaves its root')
    return path

class Parts(io.RawIOBase):

    def __init__(self, paths):
        self.paths=iter(paths); self.current=None
    def readable(self): return True
    def readinto(self, buffer):
        while True:
            if self.current is None:
                path=next(self.paths, None)
                if path is None: return 0
                self.current=path.open('rb')
            size=self.current.readinto(buffer)
            if size: return size
            self.current.close(); self.current=None
    def close(self):
        if self.current is not None: self.current.close()
        super().close()

class Recovery:
    def __init__(self, root, output=None):
        self.root=Path(root).resolve()
        data=json.loads((self.root/'RECOVERY.json').read_text())
        if data['format_version']!=1: raise ValueError('Unknown recovery format')
        self.records={r['path']:r for r in data['files']}
        if len(self.records)!=len(data['files']): raise ValueError('Duplicate recovery path')
        self.temporary=None
        if output is None:
            self.temporary=tempfile.TemporaryDirectory(prefix='.recovered-',dir=self.root)
            self.output=Path(self.temporary.name)
        else:
            self.output=Path(output).resolve()
            if self.output==self.root or self.output.is_relative_to(self.root):
                raise ValueError('Use a separate output tree, outside the repository')
            self.output.mkdir(parents=True,exist_ok=True)
        self.checked={}
    def __enter__(self): return self
    def __exit__(self,*args):
        if self.temporary is not None: self.temporary.cleanup()
    def path(self, relative):
        relative=Path(relative).as_posix()
        original=contained(self.root,relative)
        if relative not in self.records: return original
        if relative in self.checked: return self.checked[relative]
        record=self.records[relative]
        if record['encoding']!='gzip': raise ValueError('Unknown recovery encoding')
        destination=contained(self.output,relative)
        destination.parent.mkdir(parents=True,exist_ok=True)
        digest=hashlib.sha256();size=0
        descriptor,partial=tempfile.mkstemp(prefix='.recover-',dir=destination.parent)
        try:
            with os.fdopen(descriptor,'wb') as out, io.BufferedReader(Parts([contained(self.root,p) for p in record['stored_paths']]),buffer_size=BLOCK) as stored, gzip.GzipFile(fileobj=stored,mode='rb') as source:
                for block in iter(lambda:source.read(BLOCK),b''):
                    size+=len(block);digest.update(block);out.write(block)
            if digest.hexdigest()!=record['sha256'] or size!=record['bytes']:
                raise ValueError('Recovered original hash/size mismatch: '+relative)
            os.replace(partial,destination)
        finally:
            if os.path.exists(partial): os.unlink(partial)
        self.checked[relative]=destination
        return destination
    def recover_all(self):
        for relative in self.records: self.path(relative)
        return len(self.checked)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True,help='Separate directory for recovered original files')
    args=parser.parse_args()
    with Recovery(Path(__file__).resolve().parents[1],args.output) as recovery:
        count=recovery.recover_all()
    print(f'PASS: recovered and checked SHA-256 and size for {count} original files.')

if __name__=='__main__': main()
