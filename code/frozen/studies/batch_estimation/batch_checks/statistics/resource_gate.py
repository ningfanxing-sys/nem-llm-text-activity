'Measure memory and disk use during synthetic validation.'
import json
import os
from pathlib import Path
import re
import resource
import signal
import stat
import subprocess
import sys
import time

class ResourceBreach(RuntimeError):pass

class ResourceGate:
    def __init__(self,root):
        self.root=Path(root);self.samples=[];self.breaches=[];self.start=time.monotonic()
        self.old_handler=None;self.old_timer=None;self.in_sample=False
    def sample(self,*_):
        if self.in_sample:return
        self.in_sample=True
        try:
            value=subprocess.run(['/usr/bin/memory_pressure'],check=True,capture_output=True,text=True).stdout
            match=re.search(r'System-wide memory free percentage:\s*(\d+)%',value)
            if match is None:raise ResourceBreach('Cannot observe free memory')
            rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if sys.platform!='darwin':rss*=1024


            if not self.root.is_absolute() or not self.root.is_relative_to(Path('/private/tmp')) or self.root.is_symlink():
                raise ResourceBreach('Resource observation requires owned private scratch')
            module=sys.modules.get('consumer_roots');active=getattr(module,'ACTIVE',None)
            previous=getattr(active,'_resource_metadata_root',None) if active else None
            try:
                if active:active._resource_metadata_root=self.root
                records=[p.stat() for p in self.root.rglob('*') if p.is_file() and not p.is_symlink()]
                size=sum(row.st_size for row in records);seen={(row.st_dev,row.st_ino) for row in records}


                for fd in (1,2):
                    row=os.fstat(fd);key=(row.st_dev,row.st_ino)
                    if stat.S_ISREG(row.st_mode) and key not in seen:
                        size+=row.st_size;seen.add(key)
            finally:
                if active:active._resource_metadata_root=previous
            row=dict(elapsed_seconds=time.monotonic()-self.start,nice=os.getpriority(os.PRIO_PROCESS,0),memory_free_percent=int(match.group(1)),rss_bytes=rss,scratch_bytes=size)
            self.samples.append(row)
            if row['nice']!=20 or row['memory_free_percent']<25 or rss>1610612736 or size>=1000000000:
                self.breaches.append(row)
                self.checkpoint('RESOURCE_BREACH')
                raise ResourceBreach('Resource breach; checkpoint retained: '+str(row))
            return row
        finally:self.in_sample=False
    def checkpoint(self,state):
        path=self.root/'RESOURCE_CHECKPOINT.json'
        active=sys.modules.get('consumer_roots')
        active=getattr(active,'ACTIVE',None)
        native=getattr(active,'_native_scope',None) if active else None
        try:
            if active:active._native_scope=None
            path.write_text(json.dumps(dict(state=state,samples=self.samples,breaches=self.breaches),indent=2)+'\n')
        finally:
            if active:active._native_scope=native
    def __enter__(self):
        self.sample();self.old_handler=signal.signal(signal.SIGALRM,self.sample)
        self.old_timer=signal.setitimer(signal.ITIMER_REAL,5,5)
        return self
    def __exit__(self,*args):
        signal.setitimer(signal.ITIMER_REAL,*self.old_timer);signal.signal(signal.SIGALRM,self.old_handler)
        self.sample();self.checkpoint('STOPPED' if args[0] else 'OBSERVATION_COMPLETE')
    def receipt(self):
        return dict(nice=20,test_processes=1,minimum_memory_free_percent=min((r['memory_free_percent'] for r in self.samples),default=0),scratch_peak_bytes=max((r['scratch_bytes'] for r in self.samples),default=0),peak_rss_bytes=max((r['rss_bytes'] for r in self.samples),default=0),periodic_samples=self.samples,breaches=self.breaches)
