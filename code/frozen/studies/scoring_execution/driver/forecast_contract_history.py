'Compare forecast source contracts with their saved history.'
from pathlib import Path
from forecast_check_helpers import checked, document, require, row

HISTORIES = (
    ('a10/history/PREVIOUS_A9_INDEX_M.json', 53965,
     '34df9fff07e3ec31c750fc52a5d2ff437217a4ec9f614ae62c7cabd9774adfc8'),
    ('a10/history/CUMULATIVE_INDEX.json', 79926,
     'c694332f5edad3314a3cbf8b3f6808f4f746cf04405e0ca80d1f409a92eaeb8b'),
)


class ContractSources:
    def __init__(self, native, *, inventory=None, histories=None):
        self.native = native
        self.root = getattr(native, 'driver_root', Path(__file__).absolute().parent)
        self.histories = histories
        if inventory is None:
            from forecast_checks_cli import science_inventory
            build = document(row(self.root/'AF_CHAIN_BUILD.json'), native.sources)
            own = [dict(path=str(self.root/name), **pin) for name, pin in build['files'].items()]
            own.append(row(self.root/'AF_CHAIN_BUILD.json'))
            inventory = science_inventory(native, own)
        self.current = {item['path']: item for item in inventory}
        require(len(self.current) == len(inventory), 'A10b duplicate current inventory')

        if native.sources is not None:
            native.sources.recheck()
        for item in inventory:
            checked(item, native.sources)

    def verify(self, item):
        if not Path(item['path']).is_relative_to(self.root):
            return checked(item, self.native.sources)
        current = self.current.get(item['path'])
        require(current is not None, 'A10b contract source absent from current inventory')
        checked(current, self.native.sources)
        if item == current:
            return checked(item, self.native.sources)
        indices = self.histories if self.histories is not None else [
            dict(path=str(self.root/name), bytes=size, sha256=sha) for name,size,sha in HISTORIES]
        for index in indices:
            history = document(index, self.native.sources)
            for entry in history['files']:
                if entry['original'] != item:
                    continue
                archive = entry['archive']
                require(all(archive[k] == item[k] for k in ('bytes', 'sha256')),
                        'A10b historical archive identity mismatch')


                return checked(archive)
        require(False, 'A10b matching historical archive missing: '+item['path'])
