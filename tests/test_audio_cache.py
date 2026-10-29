import numpy as np
import soundfile as sf
import torch
from ming_t8.audio import load_prompt_waveform,clear_reference_cache


def test_reference_cache_does_not_mutate_source_or_reuse_changed_file(tmp_path):
    path=tmp_path/"参考.wav"
    sf.write(str(path),np.ones(16000,dtype=np.float32)*.1,16000,subtype="FLOAT")
    first=load_prompt_waveform(path,16000)
    first.zero_()
    assert torch.allclose(load_prompt_waveform(path,16000),torch.full((1,16000),.1))
    sf.write(str(path),np.ones(16000,dtype=np.float32)*.2,16000,subtype="FLOAT")
    assert torch.allclose(load_prompt_waveform(path,16000),torch.full((1,16000),.2))
    clear_reference_cache()
