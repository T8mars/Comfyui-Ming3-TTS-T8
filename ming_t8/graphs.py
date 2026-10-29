"""Optional bounded CUDA Graph cache for deterministic Flow/Aggregator forwards."""
from __future__ import annotations

from collections import OrderedDict
import inspect
import logging

import torch


class GraphForward:
    def __init__(self, method, max_graphs=4):
        self.method = method
        self.signature = inspect.signature(method)
        self.max_graphs = max_graphs
        self.cache = OrderedDict()
        self.failures = {}

    def clear(self):
        self.cache.clear()

    def __call__(self, *args, **kwargs):
        bound = self.signature.bind(*args, **kwargs)
        bound.apply_defaults()
        arguments = dict(bound.arguments)
        tensors = [value for value in arguments.values() if isinstance(value, torch.Tensor)]
        if not tensors or any(value.device.type != "cuda" for value in tensors):
            return self.method(*args, **kwargs)
        key = tuple((name, (tuple(value.shape), tuple(value.stride()), value.dtype, value.device)
                            if isinstance(value, torch.Tensor) else (type(value), value)) for name, value in arguments.items())
        # Autocast changes matmul kernels even when input tensor metadata stays equal.
        key += (("autocast",torch.is_autocast_enabled(),torch.get_autocast_dtype("cuda")),)
        if key in self.failures:
            return self.method(*args, **kwargs)
        if key not in self.cache:
            try:
                device = tensors[0].device
                static = {name:value.detach().clone() if isinstance(value,torch.Tensor) else value for name,value in arguments.items()}
                current = torch.cuda.current_stream(device)
                stream = torch.cuda.Stream(device=device)
                stream.wait_stream(current)
                with torch.cuda.stream(stream):
                    for _ in range(3):
                        self.method(**static)
                current.wait_stream(stream)
                stream.synchronize()
                graph = torch.cuda.CUDAGraph()
                with torch.cuda.graph(graph, stream=stream):
                    output = self.method(**static)
                if not isinstance(output,torch.Tensor):
                    raise TypeError("CUDA graph forward must return one tensor")
                self.cache[key] = (static,graph,output)
                while len(self.cache)>self.max_graphs:
                    self.cache.popitem(last=False)
            except Exception as error:
                self.failures[key] = str(error)
                logging.warning("Ming CUDA Graph disabled for this input shape: %s",error)
                return self.method(*args, **kwargs)
        static,graph,output = self.cache[key]
        self.cache.move_to_end(key)
        for name,value in arguments.items():
            if isinstance(value,torch.Tensor):
                static[name].copy_(value)
        graph.replay()
        return output.clone()

    def status(self):
        return {"captured_shapes":len(self.cache),"failed_shapes":list(self.failures.values())}


def install(model):
    wrappers=[]
    for module in (model.flowloss.cfm.model,model.linear_proj_audio):
        wrapper=GraphForward(module.forward)
        module.forward=wrapper
        wrappers.append(wrapper)
    return wrappers


def uninstall(wrappers):
    for wrapper in wrappers:
        module=wrapper.method.__self__
        if module.__dict__.get("forward") is wrapper:
            del module.__dict__["forward"]
        wrapper.clear()
        wrapper.method=None
    wrappers.clear()
