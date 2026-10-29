"""Windows current-process WDDM GPU accounting, including native ASR allocations.

IDXGIAdapter3::QueryVideoMemoryInfo documents CurrentUsage as process usage.
https://learn.microsoft.com/windows/win32/api/dxgi1_4/nf-dxgi1_4-idxgiadapter3-queryvideomemoryinfo
"""
from __future__ import annotations

import ctypes as C
import os
import threading
import time
import uuid


class AdapterDesc(C.Structure):
    _fields_=[("Description",C.c_wchar*128),("VendorId",C.c_uint32),("DeviceId",C.c_uint32),
        ("SubSysId",C.c_uint32),("Revision",C.c_uint32),("DedicatedVideoMemory",C.c_size_t),
        ("DedicatedSystemMemory",C.c_size_t),("SharedSystemMemory",C.c_size_t),
        ("LuidLow",C.c_uint32),("LuidHigh",C.c_int32),("Flags",C.c_uint32)]


class VideoInfo(C.Structure):
    _fields_=[("Budget",C.c_uint64),("CurrentUsage",C.c_uint64),
              ("AvailableForReservation",C.c_uint64),("CurrentReservation",C.c_uint64)]


def _guid(value):
    return (C.c_ubyte*16).from_buffer_copy(uuid.UUID(value).bytes_le)


def _method(pointer,index,restype,*argtypes):
    table=C.cast(pointer,C.POINTER(C.POINTER(C.c_void_p))).contents
    return C.WINFUNCTYPE(restype,C.c_void_p,*argtypes)(table[index])


def _release(pointer):
    if pointer and pointer.value:
        _method(pointer,2,C.c_uint32)(pointer)


class ProcessGpuMemory:
    def __init__(self):
        self.adapter=None
        self.error=None
        self.name=None
        if os.name!="nt":
            self.error="DXGI accounting is Windows-only";return
        factory=C.c_void_p()
        try:
            create=C.WinDLL("dxgi.dll").CreateDXGIFactory1
            create.argtypes=[C.c_void_p,C.POINTER(C.c_void_p)];create.restype=C.c_long
            iid=_guid("770aae78-f26f-4dba-a829-253c83d1b387")
            if create(C.byref(iid),C.byref(factory))<0:raise RuntimeError("CreateDXGIFactory1 failed")
            enumerate_adapter=_method(factory,12,C.c_long,C.c_uint32,C.POINTER(C.c_void_p))
            for index in range(32):
                adapter=C.c_void_p()
                if enumerate_adapter(factory,index,C.byref(adapter))<0:break
                try:
                    description=AdapterDesc()
                    if _method(adapter,10,C.c_long,C.POINTER(AdapterDesc))(adapter,C.byref(description))<0:continue
                    if description.VendorId!=0x10de:continue
                    selected=C.c_void_p();iid=_guid("645967a4-1392-4310-a798-8053ce3e93fd")
                    if _method(adapter,0,C.c_long,C.c_void_p,C.POINTER(C.c_void_p))(adapter,C.byref(iid),C.byref(selected))<0:continue
                    self.adapter=selected;self.name=description.Description
                    break
                finally:_release(adapter)
            if self.adapter is None:raise RuntimeError("No NVIDIA IDXGIAdapter3 found")
        except Exception as error:self.error=str(error)
        finally:_release(factory)

    def snapshot(self):
        if self.adapter is None:return {"available":False,"error":self.error}
        values=[]
        for group in (0,1):
            info=VideoInfo()
            code=_method(self.adapter,14,C.c_long,C.c_uint32,C.c_int,C.POINTER(VideoInfo))(self.adapter,0,group,C.byref(info))
            if code<0:return {"available":False,"error":f"QueryVideoMemoryInfo HRESULT {code}"}
            values.append(info)
        return {"available":True,"provider":"DXGI current-process WDDM usage","adapter":self.name,
                "local_bytes":values[0].CurrentUsage,"nonlocal_bytes":values[1].CurrentUsage,"local_budget":values[0].Budget}

    def close(self):
        pointer,self.adapter=self.adapter,None
        _release(pointer)


class MemoryMonitor:
    def __init__(self,interval=.05):
        import psutil
        self.process=psutil.Process()
        self.gpu=ProcessGpuMemory()
        self.interval=interval
        self.samples=[]
        self.stop_event=threading.Event()
        self.thread=threading.Thread(target=self._work,name="ming-process-memory",daemon=True)

    def snapshot(self):
        memory=self.process.memory_info()
        return {"time":time.time(),"rss":memory.rss,"private_bytes":getattr(memory,"private",memory.rss),"gpu":self.gpu.snapshot()}

    def _work(self):
        while not self.stop_event.is_set():
            self.samples.append(self.snapshot())
            self.stop_event.wait(self.interval)

    def start(self):
        self.thread.start();return self

    def stop(self):
        self.stop_event.set();self.thread.join(timeout=2)
        self.samples.append(self.snapshot());self.gpu.close()
        return self.samples
