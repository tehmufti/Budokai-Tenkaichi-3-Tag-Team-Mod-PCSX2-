"""Fresh, batched metadata reads inside one held Body Change transaction.

Only a page-address plan survives a native job; every byte is reread. This is
not a cache of live game state. One 128 MiB allocation replaces repeated full
allocations, and PINE batches previously discovered noncontiguous pages into
its normal bounded packets. The caller expires this object after the exchange.
"""
import lazy_ram


class Snapshot(lazy_ram.LazyRam):
    def __init__(self,client):
        super().__init__(client)
        self.used=set()

    def fetch(self,address,length):
        super().fetch(address,length)
        if length>0:self.used.update(range(address//lazy_ram.CHUNK,(address+length-1)//lazy_ram.CHUNK+1))

    def invalidate(self):
        super().invalidate()
        self.used=set()

    def renew(self, client):
        same_client=client is self.client
        # Don't accumulate an ever-growing prefetch union: a page prefetched
        # speculatively but unused by that builder is dropped at the next job.
        pages=sorted(self.used) if same_client else []
        self.invalidate()
        self.client=client
        batch=getattr(client,'read_ranges',None)
        if not pages or not callable(batch):return self
        ranges=[(i*lazy_ram.CHUNK,lazy_ram.CHUNK) for i in pages]
        data=batch(ranges)
        # Validate the whole reply before making any portion resident. Failed
        # refreshes leave poison, never a mixture of old and new metadata.
        if len(data)!=len(ranges) or any(len(value)!=length for value,(_,length) in zip(data,ranges)):
            raise IOError('Short Body Change metadata batch')
        for index,value in zip(pages,data):
            lo=index*lazy_ram.CHUNK
            bytearray.__setitem__(self,slice(lo,lo+lazy_ram.CHUNK),value)
            self.fetched[index]=1
        self.exchanges+=1
        self.bytes_fetched+=len(pages)*lazy_ram.CHUNK
        return self
