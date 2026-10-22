'Check that scoring metadata is absent from the specified directory entries.'
import errno
import os
from pathlib import PurePosixPath
import stat

from common import open_directory_metadata,require

CONTRACT_SCHEMA='FORECAST_BINDING_POSITIVE_BEFORE_T5_CONTRACT_V1'
IDENTITY_SCHEMA='FORECAST_BINDING_TIMESTAMP_DIRECTORY_ID_V1'


def _cannot(message):
    raise RuntimeError('Cannot certify before-T5: '+message)


def _absolute(value):
    if not isinstance(value,str) or not value.startswith('/') or value.startswith('//') or '\x00' in value \
       or os.path.normpath(value)!=value:
        _cannot('noncanonical source-bound path')
    return value


def _directory_id(path,metadata):
    fields=(metadata.st_dev,metadata.st_ino,metadata.st_uid,metadata.st_gid,metadata.st_mode)
    if not all(type(v) is int for v in fields) or fields[0]<0 or fields[1]<=0 \
       or fields[2]<0 or fields[3]<0 or not stat.S_ISDIR(fields[4]):
        _cannot('unverifiable real directory identity')
    return dict(schema=IDENTITY_SCHEMA,path=path,device=fields[0],inode=fields[1],
                uid=fields[2],gid=fields[3],mode=fields[4])


def _validate_contract(contract):
    require(isinstance(contract,dict) and set(contract)=={'schema','timestamp_root','timestamp_label',
            'timestamp_label_path','sentinel_paths','score_receipts'} and contract.get('schema')==CONTRACT_SCHEMA,
            'Cannot certify before-T5: exact source contract required')
    root=_absolute(contract['timestamp_root'])
    require(contract.get('timestamp_label')=='T5' and contract.get('timestamp_label_path')==root+'/T5',
            'Cannot certify before-T5: exact T5 label required')
    sentinels=contract['sentinel_paths']
    require(isinstance(sentinels,list) and sentinels,
            'Cannot certify before-T5: nonempty unique gate set required')
    for path in sentinels:_absolute(path)
    require(len(sentinels)==len(set(sentinels)),
            'Cannot certify before-T5: nonempty unique gate set required')
    require(root+'/T5' not in sentinels,'Cannot certify before-T5: duplicate timestamp leaf')
    receipts=contract['score_receipts']
    require(isinstance(receipts,list) and receipts,'Cannot certify before-T5: score receipt coverage required')
    seen=set()
    for row in receipts:
        require(isinstance(row,dict) and set(row)=={'path','absent_namespace'},
                'Cannot certify before-T5: malformed score namespace binding')
        path=_absolute(row['path']);parent=_absolute(row['absent_namespace'])
        require(parent in sentinels and (path==parent or path.startswith(parent+'/')) and path not in seen,
                'Cannot certify before-T5: unbound score receipt')
        seen.add(path)
    return root,[root+'/T5',*sentinels]


class _DirectoryChain:

    def __init__(self):
        self.nodes={};self.order=[]

    def __enter__(self):return self

    def __exit__(self,*args):
        error=None
        for path in reversed(self.order):
            try:os.close(self.nodes[path]['fd'])
            except OSError as exc:error=exc
        if error is not None:
            raise RuntimeError('Cannot certify before-T5: directory descriptor close failure') from error

    def directory(self,path):
        path=_absolute(path)
        if path in self.nodes:return self.nodes[path]
        if '/' not in self.nodes:
            fd=open_directory_metadata('/')
            try:
                identity=_directory_id('/',os.fstat(fd));os.listdir(fd)
            except BaseException:
                os.close(fd);raise
            self.nodes['/']=dict(fd=fd,identity=identity,parent=None,name=None)
            self.order.append('/')
        current='/'
        for name in PurePosixPath(path).parts[1:]:
            child=os.path.join(current,name)
            if child not in self.nodes:
                parent=self.nodes[current]
                metadata=os.stat(name,dir_fd=parent['fd'],follow_symlinks=False)
                identity=_directory_id(child,metadata)
                fd=open_directory_metadata(name,dir_fd=parent['fd'],parent_path=current)
                try:
                    require(_directory_id(child,os.fstat(fd))==identity,
                            'Cannot certify before-T5: directory changed while opening')
                    os.listdir(fd)
                except BaseException:
                    os.close(fd);raise
                self.nodes[child]=dict(fd=fd,identity=identity,parent=current,name=name)
                self.order.append(child)
            current=child
        return self.nodes[path]

    def revalidate(self):
        for path in self.order:
            node=self.nodes[path]
            require(_directory_id(path,os.fstat(node['fd']))==node['identity'],
                    'Cannot certify before-T5: retained directory identity changed')
            if node['parent'] is not None:
                parent=self.nodes[node['parent']]
                actual=os.stat(node['name'],dir_fd=parent['fd'],follow_symlinks=False)
                require(_directory_id(path,actual)==node['identity'],
                        'Cannot certify before-T5: parent/path identity changed')

    def absent(self,path):
        path=_absolute(path);parent_path,name=os.path.split(path)
        require(name not in ('','.','..'),'Cannot certify before-T5: invalid absent leaf')
        parent=self.directory(parent_path)
        names=os.listdir(parent['fd'])
        require(name not in names,'Associated T5/scoring state already exists')
        try:
            os.stat(name,dir_fd=parent['fd'],follow_symlinks=False)
        except FileNotFoundError as exc:
            if exc.errno!=errno.ENOENT:raise


            return parent['identity']
        _cannot('Associated T5/scoring state already exists')


def capture_timestamp_identity(contract):

    root,_=_validate_contract(contract)
    try:
        with _DirectoryChain() as chain:
            identity=dict(chain.directory(root)['identity'])
            chain.revalidate()
            return identity
    except (OSError,AttributeError,TypeError,ValueError) as exc:
        raise RuntimeError('Cannot certify before-T5: timestamp directory identity unavailable') from exc


def prove_before_t5(contract,expected_timestamp_identity):

    root,gates=_validate_contract(contract)
    require(isinstance(expected_timestamp_identity,dict) and
            set(expected_timestamp_identity)=={'schema','path','device','inode','uid','gid','mode'}
            and expected_timestamp_identity['schema']==IDENTITY_SCHEMA
            and expected_timestamp_identity['path']==root,
            'Cannot certify before-T5: bound timestamp directory identity required')
    require(all(type(expected_timestamp_identity[k]) is int for k in ('device','inode','uid','gid','mode'))
            and expected_timestamp_identity['device']>=0 and expected_timestamp_identity['inode']>0
            and expected_timestamp_identity['uid']>=0 and expected_timestamp_identity['gid']>=0
            and stat.S_ISDIR(expected_timestamp_identity['mode']),
            'Cannot certify before-T5: unverifiable expected directory identity')
    try:
        with _DirectoryChain() as chain:
            timestamp=chain.directory(root)['identity']
            require(timestamp==expected_timestamp_identity,
                    'Cannot certify before-T5: bound timestamp directory identity drift')
            parents=[dict(chain.absent(path)) for path in gates]
            chain.revalidate()

            for path in gates:chain.absent(path)
            chain.revalidate()
            require(chain.directory(root)['identity']==expected_timestamp_identity,
                    'Cannot certify before-T5: timestamp identity changed')
            return dict(schema='FORECAST_BINDING_POSITIVE_BEFORE_T5_V1',
                        timestamp_root_identity=dict(timestamp),
                        checked_absent_paths=gates,parent_identities=parents,
                        checks=dict(exact_T5_label_absent=True,score_receipts_absent=True,
                                    source_bound_real_root=True,no_links_followed=True,
                                    readable_parents_verified=True,parent_chain_stable=True,
                                    second_leaf_check=True),
                        receipt_contents_opened=False,locks_opened_or_acquired=False,
                        proof_scope='positive directory-metadata snapshot; source serial order remains required')
    except (OSError,AttributeError,TypeError,ValueError) as exc:
        raise RuntimeError('Cannot certify before-T5: directory/leaf metadata check failed') from exc
